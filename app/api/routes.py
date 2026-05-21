from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_admin
from app.core.config import settings
from app.db.models import AuditLog, ScheduleVersion
from app.schemas import (
    LoginRequest,
    LoginResponse,
    ReviewWindowRequest,
    SaveAssignmentsRequest,
    StartPickingRequest,
    SubmitPickRequest,
)
from app.services.schedule_service import (
    close_review_window,
    create_month_if_missing,
    create_session,
    diff_snapshots,
    end_session,
    get_schedule_month_or_404,
    month_summary,
    open_review_window,
    save_review_assignments,
    submit_initial_pick,
)

api_router = APIRouter()


@api_router.get("/")
def read_root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "ok",
    }


@api_router.get("/healthz")
def read_healthz() -> dict[str, str]:
    return {
        "status": "ok",
        "database": str(settings.database_path.resolve()),
    }


@api_router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    token, user = create_session(db, payload.employee_id)
    return LoginResponse(
        token=token,
        session_header=settings.session_header_name,
        user={
            "employee_id": user.employee_id,
            "name": user.name,
            "role": user.role,
            "holiday_fixed_off": user.holiday_fixed_off,
        },
    )


@api_router.post("/logout")
def logout(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    token = x_session_token
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="缺少 session token")
    end_session(db, token, current_user.employee_id)
    return {"status": "ok"}


@api_router.get("/me")
def me(current_user=Depends(get_current_user)) -> dict:
    return {
        "employee_id": current_user.employee_id,
        "name": current_user.name,
        "role": current_user.role,
        "holiday_fixed_off": current_user.holiday_fixed_off,
    }


@api_router.get("/months/{year}/{month}")
def get_month(
    year: int,
    month: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    schedule_month = get_schedule_month_or_404(db, year, month)
    return month_summary(db, schedule_month, current_user)


@api_router.post("/months/{year}/{month}/start-picking")
def start_picking(
    year: int,
    month: int,
    payload: StartPickingRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    schedule_month = create_month_if_missing(db, year, month, current_user.employee_id)
    schedule_month.status = "picking"
    if schedule_month.review_deadline is None:
        schedule_month.review_deadline = payload.review_deadline
    db.commit()
    return month_summary(db, schedule_month, current_user)


@api_router.post("/months/{year}/{month}/picks/submit")
def submit_picks(
    year: int,
    month: int,
    payload: SubmitPickRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    schedule_month = get_schedule_month_or_404(db, year, month)
    target_employee_id = payload.employee_id or current_user.employee_id
    return submit_initial_pick(
        db,
        schedule_month,
        current_user,
        target_employee_id,
        payload.holiday_dates,
        payload.comp_dates,
        payload.carryover_count,
    )


@api_router.post("/months/{year}/{month}/review-window/open")
def review_window_open(
    year: int,
    month: int,
    payload: ReviewWindowRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    schedule_month = get_schedule_month_or_404(db, year, month)
    return open_review_window(db, schedule_month, current_user, payload.review_deadline)


@api_router.post("/months/{year}/{month}/review-window/close")
def review_window_close(
    year: int,
    month: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    schedule_month = get_schedule_month_or_404(db, year, month)
    return close_review_window(db, schedule_month, current_user)


@api_router.post("/months/{year}/{month}/assignments/save")
def save_assignments(
    year: int,
    month: int,
    payload: SaveAssignmentsRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    schedule_month = get_schedule_month_or_404(db, year, month)
    return save_review_assignments(
        db,
        schedule_month,
        current_user,
        payload.version_number,
        payload.override_mode,
        payload.holiday_assignments,
        payload.comp_assignments,
        payload.capacities,
        [item.model_dump() for item in payload.pending_carryovers],
    )


@api_router.get("/months/{year}/{month}/versions")
def list_versions(
    year: int,
    month: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    schedule_month = get_schedule_month_or_404(db, year, month)
    versions = db.scalars(
        select(ScheduleVersion)
        .where(ScheduleVersion.schedule_month_id == schedule_month.id)
        .order_by(ScheduleVersion.version_number.desc())
    ).all()
    return {
        "items": [
            {
                "id": version.id,
                "version_number": version.version_number,
                "version_name": version.version_name,
                "created_by": version.created_by,
                "created_at": version.created_at.isoformat(),
                "source": version.source,
            }
            for version in versions
        ]
    }


@api_router.get("/months/{year}/{month}/versions/{version_id}")
def get_version(
    year: int,
    month: int,
    version_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    schedule_month = get_schedule_month_or_404(db, year, month)
    version = db.scalar(
        select(ScheduleVersion).where(
            ScheduleVersion.schedule_month_id == schedule_month.id,
            ScheduleVersion.id == version_id,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="找不到版本")
    return {
        "id": version.id,
        "version_number": version.version_number,
        "version_name": version.version_name,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat(),
        "source": version.source,
        "snapshot": version.snapshot,
    }


@api_router.get("/months/{year}/{month}/diff")
def get_diff(
    year: int,
    month: int,
    from_version: int = Query(alias="from"),
    to_version: int = Query(alias="to"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    schedule_month = get_schedule_month_or_404(db, year, month)
    versions = db.scalars(
        select(ScheduleVersion).where(
            ScheduleVersion.schedule_month_id == schedule_month.id,
            ScheduleVersion.id.in_([from_version, to_version]),
        )
    ).all()
    version_map = {version.id: version for version in versions}
    if from_version not in version_map or to_version not in version_map:
        raise HTTPException(status_code=404, detail="比較版本不存在")
    return {
        "from_version": version_map[from_version].version_name,
        "to_version": version_map[to_version].version_name,
        "diff": diff_snapshots(version_map[from_version].snapshot, version_map[to_version].snapshot),
    }


@api_router.get("/audit-logs")
def get_audit_logs(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    logs = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()
    return {
        "items": [
            {
                "id": log.id,
                "actor_id": log.actor_id,
                "action_type": log.action_type,
                "year": log.year,
                "month": log.month,
                "schedule_month_id": log.schedule_month_id,
                "before_payload": log.before_payload,
                "after_payload": log.after_payload,
                "affected_users": log.affected_users,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    }
