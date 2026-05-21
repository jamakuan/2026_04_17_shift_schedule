from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime
import calendar
import secrets
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AppMetadata,
    Assignment,
    AuditLog,
    AuthSession,
    CompOffCapacity,
    HolidayDate,
    MonthParticipant,
    PendingCarryover,
    ScheduleMonth,
    ScheduleVersion,
    User,
)


DEFAULT_USERS = [
    {"employee_id": "2191", "name": "王宏榮", "role": "employee", "holiday_fixed_off": True},
    {"employee_id": "2196", "name": "鍾靜怡", "role": "admin", "holiday_fixed_off": False},
    {"employee_id": "2138", "name": "許芷嘉", "role": "employee", "holiday_fixed_off": False},
    {"employee_id": "2318", "name": "黃柏瑜", "role": "employee", "holiday_fixed_off": False},
    {"employee_id": "2442", "name": "彭盛寬", "role": "employee", "holiday_fixed_off": False},
]

INITIAL_DUTY_ORDER = ["2196", "2138", "2318", "2442"]

NATIONAL_HOLIDAYS = {
    "2026-01-01": "開國紀念日",
    "2026-02-15": "小年夜",
    "2026-02-16": "農曆除夕",
    "2026-02-17": "春節",
    "2026-02-18": "春節",
    "2026-02-19": "春節",
    "2026-02-20": "補假",
    "2026-02-27": "補假",
    "2026-02-28": "和平紀念日",
    "2026-04-03": "補假",
    "2026-04-04": "兒童節",
    "2026-04-05": "清明節",
    "2026-04-06": "補假",
    "2026-05-01": "勞動節",
    "2026-06-19": "端午節",
    "2026-09-25": "中秋節",
    "2026-09-28": "孔子誕辰紀念日 / 教師節",
    "2026-10-09": "補假",
    "2026-10-10": "國慶日",
    "2026-10-25": "臺灣光復暨金門古寧頭大捷紀念日",
    "2026-10-26": "補假",
    "2026-12-25": "行憲紀念日",
}


def bootstrap_defaults(db: Session) -> None:
    existing = {user.employee_id for user in db.scalars(select(User)).all()}
    for payload in DEFAULT_USERS:
        if payload["employee_id"] not in existing:
            db.add(User(**payload))

    if db.get(AppMetadata, "default_frontend") is None:
        db.add(AppMetadata(key="default_frontend", value="Year_Month_Schedule_Title.html"))
    db.commit()


def format_date_key(year: int, month: int, day: int) -> str:
    return f"{year}-{month:02d}-{day:02d}"


def previous_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def next_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def validate_year_month(year: int, month: int) -> None:
    if year < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="年份必須大於 0")
    if month < 1 or month > 12:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="月份必須介於 1 到 12")


def get_days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def get_weekday(year: int, month: int, day: int) -> int:
    return date(year, month, day).weekday()


def is_sunday(year: int, month: int, day: int) -> bool:
    return date(year, month, day).weekday() == 6


def is_saturday(year: int, month: int, day: int) -> bool:
    return date(year, month, day).weekday() == 5


def get_holiday_name(year: int, month: int, day: int) -> str:
    return NATIONAL_HOLIDAYS.get(format_date_key(year, month, day), "")


def is_national_holiday(year: int, month: int, day: int) -> bool:
    return bool(get_holiday_name(year, month, day))


def is_duty_holiday(year: int, month: int, day: int) -> bool:
    if is_sunday(year, month, day):
        return False
    return is_saturday(year, month, day) or is_national_holiday(year, month, day)


def get_duty_dates(year: int, month: int) -> list[str]:
    return [
        format_date_key(year, month, day)
        for day in range(1, get_days_in_month(year, month) + 1)
        if is_duty_holiday(year, month, day)
    ]


def get_comp_dates(year: int, month: int) -> list[str]:
    return [
        format_date_key(year, month, day)
        for day in range(1, get_days_in_month(year, month) + 1)
        if not is_saturday(year, month, day)
        and not is_sunday(year, month, day)
        and not is_national_holiday(year, month, day)
    ]


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def list_participants(db: Session, schedule_month_id: int) -> list[MonthParticipant]:
    return db.scalars(
        select(MonthParticipant)
        .where(MonthParticipant.schedule_month_id == schedule_month_id)
        .order_by(MonthParticipant.pick_order.asc())
    ).all()


def list_assignments(db: Session, schedule_month_id: int) -> list[Assignment]:
    return db.scalars(
        select(Assignment).where(Assignment.schedule_month_id == schedule_month_id)
    ).all()


def list_carryovers(db: Session, schedule_month_id: int) -> list[PendingCarryover]:
    return db.scalars(
        select(PendingCarryover).where(PendingCarryover.schedule_month_id == schedule_month_id)
    ).all()


def list_capacities(db: Session, schedule_month_id: int) -> list[CompOffCapacity]:
    return db.scalars(
        select(CompOffCapacity)
        .where(CompOffCapacity.schedule_month_id == schedule_month_id)
        .order_by(CompOffCapacity.date.asc())
    ).all()


def get_schedule_month_or_404(db: Session, year: int, month: int) -> ScheduleMonth:
    schedule_month = db.scalar(
        select(ScheduleMonth).where(
            ScheduleMonth.year == year,
            ScheduleMonth.month == month,
        )
    )
    if schedule_month is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="月份尚未建立")
    return schedule_month


def create_session(db: Session, employee_id: str) -> tuple[str, User]:
    user = db.get(User, employee_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到可登入的員工編號")

    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token=token, employee_id=user.employee_id))
    log_action(
        db,
        user.employee_id,
        "login",
        None,
        None,
        None,
        None,
        None,
        [user.employee_id],
        commit=False,
    )
    db.commit()
    return token, user


def end_session(db: Session, token: str, actor_id: str) -> None:
    auth_session = db.get(AuthSession, token)
    if auth_session is None or auth_session.ended_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="登入狀態不存在")
    auth_session.ended_at = datetime.now(UTC)
    log_action(
        db,
        actor_id,
        "logout",
        None,
        None,
        None,
        None,
        None,
        [actor_id],
        commit=False,
    )
    db.commit()


def get_user_map(db: Session) -> dict[str, User]:
    return {user.employee_id: user for user in db.scalars(select(User)).all()}


def compute_next_order_from_previous_month(
    db: Session,
    year: int,
    month: int,
) -> list[str]:
    prev_year, prev_month = previous_year_month(year, month)
    previous_record = db.scalar(
        select(ScheduleMonth).where(
            ScheduleMonth.year == prev_year,
            ScheduleMonth.month == prev_month,
        )
    )
    if previous_record is None:
        return INITIAL_DUTY_ORDER[:]

    participants = list_participants(db, previous_record.id)
    if not participants:
        return INITIAL_DUTY_ORDER[:]

    order_index = {participant.user_id: participant.pick_order for participant in participants}
    counts = Counter()
    assignments = list_assignments(db, previous_record.id)
    holiday_assignments = [item for item in assignments if item.assignment_type == "holiday_duty"]
    if holiday_assignments:
        for item in holiday_assignments:
            counts[item.user_id] += 1
    else:
        for participant in participants:
            counts[participant.user_id] = participant.holiday_quota

    return [
        participant.user_id
        for participant in sorted(
            participants,
            key=lambda item: (counts[item.user_id], order_index[item.user_id]),
        )
    ]


def create_month_if_missing(db: Session, year: int, month: int, actor_id: str) -> ScheduleMonth:
    validate_year_month(year, month)
    schedule_month = db.scalar(
        select(ScheduleMonth).where(
            ScheduleMonth.year == year,
            ScheduleMonth.month == month,
        )
    )
    if schedule_month is not None:
        return schedule_month

    order = compute_next_order_from_previous_month(db, year, month)
    duty_dates = get_duty_dates(year, month)
    comp_dates = get_comp_dates(year, month)
    base = len(duty_dates) // len(order)
    remainder = len(duty_dates) % len(order)

    schedule_month = ScheduleMonth(
        year=year,
        month=month,
        status="draft",
        current_picker_id=order[0] if order else None,
        created_by=actor_id,
    )
    db.add(schedule_month)
    db.flush()

    user_map = get_user_map(db)
    for index, user_id in enumerate(order):
        quota = base + (1 if index < remainder else 0)
        db.add(
            MonthParticipant(
                schedule_month_id=schedule_month.id,
                user_id=user_id,
                pick_order=index + 1,
                holiday_quota=quota,
                comp_quota=quota,
            )
        )

    for duty_date in duty_dates:
        parsed = parse_date(duty_date)
        db.add(
            HolidayDate(
                schedule_month_id=schedule_month.id,
                date=duty_date,
                label=get_holiday_name(year, month, parsed.day) or ("週六" if is_saturday(year, month, parsed.day) else None),
                is_national_holiday=is_national_holiday(year, month, parsed.day),
                is_saturday=is_saturday(year, month, parsed.day),
            )
        )

    for comp_date in comp_dates:
        db.add(
            CompOffCapacity(
                schedule_month_id=schedule_month.id,
                date=comp_date,
                capacity=1,
            )
        )

    log_action(
        db,
        actor_id,
        "month_created",
        schedule_month.id,
        year,
        month,
        None,
        {"participants": [user_map[user_id].name for user_id in order]},
        order,
        commit=False,
    )
    db.commit()
    return schedule_month


def log_action(
    db: Session,
    actor_id: str | None,
    action_type: str,
    schedule_month_id: int | None,
    year: int | None,
    month: int | None,
    before_payload: Any,
    after_payload: Any,
    affected_users: list[str] | None,
    *,
    commit: bool = True,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action_type=action_type,
            schedule_month_id=schedule_month_id,
            year=year,
            month=month,
            before_payload=before_payload,
            after_payload=after_payload,
            affected_users=affected_users,
        )
    )
    if commit:
        db.commit()


def is_review_deadline_expired(schedule_month: ScheduleMonth) -> bool:
    deadline = schedule_month.review_deadline
    if deadline is None:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return datetime.now(UTC) > deadline


def month_summary(
    db: Session,
    schedule_month: ScheduleMonth,
    current_user: User,
) -> dict[str, Any]:
    participants = list_participants(db, schedule_month.id)
    user_map = get_user_map(db)
    assignments = list_assignments(db, schedule_month.id)
    carryovers = list_carryovers(db, schedule_month.id)
    capacities = list_capacities(db, schedule_month.id)
    holiday_dates = db.scalars(
        select(HolidayDate)
        .where(HolidayDate.schedule_month_id == schedule_month.id)
        .order_by(HolidayDate.date.asc())
    ).all()

    holiday_by_user: dict[str, list[str]] = defaultdict(list)
    comp_by_user: dict[str, list[str]] = defaultdict(list)
    holiday_assigned_by_date: dict[str, str] = {}
    comp_usage_by_date: dict[str, list[str]] = defaultdict(list)
    for item in assignments:
        if item.assignment_type == "holiday_duty":
            holiday_by_user[item.user_id].append(item.date)
            holiday_assigned_by_date[item.date] = item.user_id
        else:
            comp_by_user[item.user_id].append(item.date)
            comp_usage_by_date[item.date].append(item.user_id)

    participant_payload = []
    for participant in participants:
        participant_payload.append(
            {
                "employee_id": participant.user_id,
                "name": user_map[participant.user_id].name,
                "role": user_map[participant.user_id].role,
                "pick_order": participant.pick_order,
                "holiday_quota": participant.holiday_quota,
                "comp_quota": participant.comp_quota,
                "completed": participant.has_completed_initial_pick,
                "holiday_dates": sorted(holiday_by_user[participant.user_id]),
                "comp_dates": sorted(comp_by_user[participant.user_id]),
                "carryovers": sorted(
                    [
                        carryover.source_holiday_date
                        for carryover in carryovers
                        if carryover.user_id == participant.user_id
                    ]
                ),
            }
        )

    current_picker_name = (
        user_map[schedule_month.current_picker_id].name
        if schedule_month.current_picker_id and schedule_month.current_picker_id in user_map
        else None
    )

    remaining_capacities = []
    for capacity in capacities:
        used = len(comp_usage_by_date.get(capacity.date, []))
        remaining_capacities.append(
            {
                "date": capacity.date,
                "capacity": capacity.capacity,
                "used": used,
                "remaining": capacity.capacity - used,
            }
        )

    version_exists = schedule_month.latest_version_number > 0
    review_deadline_expired = is_review_deadline_expired(schedule_month)
    return {
        "year": schedule_month.year,
        "month": schedule_month.month,
        "status": schedule_month.status,
        "current_picker_id": schedule_month.current_picker_id,
        "current_picker_name": current_picker_name,
        "review_deadline": schedule_month.review_deadline.isoformat() if schedule_month.review_deadline else None,
        "review_deadline_expired": review_deadline_expired,
        "latest_version_number": schedule_month.latest_version_number,
        "participants": participant_payload,
        "holiday_dates": [
            {
                "date": item.date,
                "label": item.label,
                "is_national_holiday": item.is_national_holiday,
                "is_saturday": item.is_saturday,
                "assigned_to": holiday_assigned_by_date.get(item.date),
            }
            for item in holiday_dates
        ],
        "comp_dates": remaining_capacities,
        "carryovers": [
            {
                "employee_id": carryover.user_id,
                "employee_name": user_map[carryover.user_id].name,
                "source_holiday_date": carryover.source_holiday_date,
                "requested_target_month": carryover.requested_target_month,
            }
            for carryover in carryovers
        ],
        "assignments": {
            "holiday": holiday_assigned_by_date,
            "comp": {date_key: users for date_key, users in sorted(comp_usage_by_date.items())},
        },
        "permissions": {
            "is_admin": current_user.role == "admin",
            "can_submit_pick": bool(
                schedule_month.status == "picking"
                and (
                    current_user.role == "admin"
                    or current_user.employee_id == schedule_month.current_picker_id
                )
            ),
            "can_edit_all": bool(
                (
                    schedule_month.status == "review_open"
                    and (
                        current_user.role == "admin"
                        or not review_deadline_expired
                    )
                )
                or (schedule_month.status == "locked" and current_user.role == "admin")
            ),
            "can_manage_month": current_user.role == "admin",
            "can_view_versions": version_exists,
        },
    }


def create_snapshot(db: Session, schedule_month: ScheduleMonth) -> dict[str, Any]:
    participants = list_participants(db, schedule_month.id)
    assignments = list_assignments(db, schedule_month.id)
    carryovers = list_carryovers(db, schedule_month.id)
    capacities = list_capacities(db, schedule_month.id)
    users = get_user_map(db)

    return {
        "year": schedule_month.year,
        "month": schedule_month.month,
        "status": schedule_month.status,
        "current_picker_id": schedule_month.current_picker_id,
        "latest_version_number": schedule_month.latest_version_number,
        "participants": [
            {
                "employee_id": participant.user_id,
                "name": users[participant.user_id].name,
                "pick_order": participant.pick_order,
                "holiday_quota": participant.holiday_quota,
                "comp_quota": participant.comp_quota,
                "completed": participant.has_completed_initial_pick,
            }
            for participant in participants
        ],
        "assignments": [
            {
                "employee_id": item.user_id,
                "date": item.date,
                "assignment_type": item.assignment_type,
                "source_holiday_date": item.source_holiday_date,
            }
            for item in sorted(assignments, key=lambda entry: (entry.assignment_type, entry.date, entry.user_id))
        ],
        "comp_capacities": [
            {"date": item.date, "capacity": item.capacity}
            for item in capacities
        ],
        "pending_carryovers": [
            {
                "employee_id": item.user_id,
                "source_holiday_date": item.source_holiday_date,
                "requested_target_month": item.requested_target_month,
            }
            for item in sorted(carryovers, key=lambda entry: (entry.user_id, entry.source_holiday_date))
        ],
    }


def create_version(
    db: Session,
    schedule_month: ScheduleMonth,
    actor_id: str,
    source: str,
) -> ScheduleVersion:
    actor = db.get(User, actor_id)
    timestamp = datetime.now(UTC)
    version_number = schedule_month.latest_version_number + 1
    schedule_month.latest_version_number = version_number
    db.flush()
    snapshot = create_snapshot(db, schedule_month)
    version = ScheduleVersion(
        schedule_month_id=schedule_month.id,
        version_number=version_number,
        version_name=f"{timestamp.strftime('%Y%m%d-%H%M')}_{actor.name}",
        created_by=actor_id,
        source=source,
        snapshot=snapshot,
    )
    db.add(version)
    db.flush()
    return version


def sorted_date_list(values: list[str]) -> list[str]:
    return sorted(values, key=parse_date)


def ensure_initial_pick_permissions(
    schedule_month: ScheduleMonth,
    actor: User,
    target_employee_id: str,
) -> None:
    if schedule_month.status != "picking":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="目前不在順序選填階段")
    if actor.role != "admin" and target_employee_id != actor.employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能提交自己的選填結果")
    if actor.role != "admin" and schedule_month.current_picker_id != actor.employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="尚未輪到你")


def validate_pick_dates(
    holiday_dates: list[str],
    comp_dates: list[str],
    carryover_count: int,
) -> None:
    ordered_holidays = sorted_date_list(holiday_dates)
    ordered_comp_dates = sorted_date_list(comp_dates)
    if carryover_count < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="跨月補休數不可小於 0")
    if len(ordered_comp_dates) + carryover_count != len(ordered_holidays):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="補休數量必須與值班數量一致")
    for index, comp_date in enumerate(ordered_comp_dates):
        if parse_date(comp_date) <= parse_date(ordered_holidays[index]):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="補休日必須晚於排序對應的假日值班日",
            )


def submit_initial_pick(
    db: Session,
    schedule_month: ScheduleMonth,
    actor: User,
    target_employee_id: str,
    holiday_dates: list[str],
    comp_dates: list[str],
    carryover_count: int,
) -> dict[str, Any]:
    ensure_initial_pick_permissions(schedule_month, actor, target_employee_id)

    participant = db.scalar(
        select(MonthParticipant).where(
            MonthParticipant.schedule_month_id == schedule_month.id,
            MonthParticipant.user_id == target_employee_id,
        )
    )
    if participant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到本月參與者")
    if participant.has_completed_initial_pick:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="此參與者已完成初次選填")

    holiday_set = set(holiday_dates)
    comp_set = set(comp_dates)
    if len(holiday_set) != len(holiday_dates) or len(comp_set) != len(comp_dates):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="提交資料不可有重複日期")
    if len(holiday_dates) != participant.holiday_quota:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="值班日數量不符 quota")

    month_holiday_dates = {
        item.date
        for item in db.scalars(
            select(HolidayDate).where(HolidayDate.schedule_month_id == schedule_month.id)
        ).all()
    }
    if not holiday_set.issubset(month_holiday_dates):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="包含非本月可值班日期")

    capacity_records = {item.date: item for item in list_capacities(db, schedule_month.id)}
    if not comp_set.issubset(capacity_records.keys()):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="包含非本月可補休日")

    validate_pick_dates(holiday_dates, comp_dates, carryover_count)

    current_assignments = list_assignments(db, schedule_month.id)
    occupied_holiday_dates = {
        item.date
        for item in current_assignments
        if item.assignment_type == "holiday_duty" and item.user_id != target_employee_id
    }
    if holiday_set & occupied_holiday_dates:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="包含已被占用的值班日期")

    comp_usage = Counter(
        item.date
        for item in current_assignments
        if item.assignment_type == "comp_day_off" and item.user_id != target_employee_id
    )
    for comp_date in comp_dates:
        if comp_usage[comp_date] + 1 > capacity_records[comp_date].capacity:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="補休日已超出日期容量")

    for holiday_date in holiday_dates:
        db.add(
            Assignment(
                schedule_month_id=schedule_month.id,
                user_id=target_employee_id,
                date=holiday_date,
                assignment_type="holiday_duty",
            )
        )
    for comp_date in comp_dates:
        db.add(
            Assignment(
                schedule_month_id=schedule_month.id,
                user_id=target_employee_id,
                date=comp_date,
                assignment_type="comp_day_off",
            )
        )

    if carryover_count > 0:
        next_year, next_month = next_year_month(schedule_month.year, schedule_month.month)
        for holiday_date in sorted_date_list(holiday_dates)[-carryover_count:]:
            db.add(
                PendingCarryover(
                    schedule_month_id=schedule_month.id,
                    user_id=target_employee_id,
                    source_holiday_date=holiday_date,
                    requested_target_month=f"{next_year}-{next_month:02d}",
                    created_by=actor.employee_id,
                )
            )

    participant.has_completed_initial_pick = True
    remaining = [
        item.user_id
        for item in list_participants(db, schedule_month.id)
        if not item.has_completed_initial_pick and item.user_id != target_employee_id
    ]
    schedule_month.current_picker_id = remaining[0] if remaining else None

    version: ScheduleVersion | None = None
    if not remaining and schedule_month.latest_version_number == 0:
        version = create_version(db, schedule_month, actor.employee_id, "initial_picking_complete")

    log_action(
        db,
        actor.employee_id,
        "submit_pick",
        schedule_month.id,
        schedule_month.year,
        schedule_month.month,
        None,
        {
            "target_employee_id": target_employee_id,
            "holiday_dates": sorted_date_list(holiday_dates),
            "comp_dates": sorted_date_list(comp_dates),
            "carryover_count": carryover_count,
            "version_number": version.version_number if version else schedule_month.latest_version_number,
        },
        [target_employee_id],
        commit=False,
    )
    db.commit()

    return {
        "status": schedule_month.status,
        "current_picker_id": schedule_month.current_picker_id,
        "latest_version_number": schedule_month.latest_version_number,
    }


def open_review_window(
    db: Session,
    schedule_month: ScheduleMonth,
    actor: User,
    review_deadline: datetime | None,
) -> dict[str, Any]:
    participants = list_participants(db, schedule_month.id)
    if any(not participant.has_completed_initial_pick for participant in participants):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="尚未完成全員初次選填")

    before_status = schedule_month.status
    schedule_month.status = "review_open"
    schedule_month.review_opened_at = datetime.now(UTC)
    schedule_month.review_deadline = review_deadline
    log_action(
        db,
        actor.employee_id,
        "review_window_open",
        schedule_month.id,
        schedule_month.year,
        schedule_month.month,
        {"status": before_status},
        {"status": schedule_month.status, "review_deadline": review_deadline.isoformat() if review_deadline else None},
        None,
        commit=False,
    )
    db.commit()
    return {"status": schedule_month.status}


def close_review_window(db: Session, schedule_month: ScheduleMonth, actor: User) -> dict[str, Any]:
    before_status = schedule_month.status
    schedule_month.status = "locked"
    schedule_month.locked_at = datetime.now(UTC)
    log_action(
        db,
        actor.employee_id,
        "review_window_close",
        schedule_month.id,
        schedule_month.year,
        schedule_month.month,
        {"status": before_status},
        {"status": schedule_month.status},
        None,
        commit=False,
    )
    db.commit()
    return {"status": schedule_month.status}


def snapshot_to_maps(snapshot: dict[str, Any]) -> dict[str, Any]:
    holiday_map = {}
    comp_map: dict[str, list[str]] = defaultdict(list)
    for item in snapshot.get("assignments", []):
        if item["assignment_type"] == "holiday_duty":
            holiday_map[item["date"]] = item["employee_id"]
        else:
            comp_map[item["date"]].append(item["employee_id"])
    return {
        "holiday": holiday_map,
        "comp": {key: sorted(values) for key, values in comp_map.items()},
        "capacities": {
            item["date"]: item["capacity"]
            for item in snapshot.get("comp_capacities", [])
        },
        "carryovers": {
            (item["employee_id"], item["source_holiday_date"]): item.get("requested_target_month")
            for item in snapshot.get("pending_carryovers", [])
        },
    }


def diff_snapshots(from_snapshot: dict[str, Any], to_snapshot: dict[str, Any]) -> dict[str, Any]:
    from_maps = snapshot_to_maps(from_snapshot)
    to_maps = snapshot_to_maps(to_snapshot)

    holiday_changes = []
    for duty_date in sorted(set(from_maps["holiday"]) | set(to_maps["holiday"])):
        if from_maps["holiday"].get(duty_date) != to_maps["holiday"].get(duty_date):
            holiday_changes.append(
                {
                    "date": duty_date,
                    "from": from_maps["holiday"].get(duty_date),
                    "to": to_maps["holiday"].get(duty_date),
                }
            )

    comp_changes = []
    for comp_date in sorted(set(from_maps["comp"]) | set(to_maps["comp"])):
        if from_maps["comp"].get(comp_date, []) != to_maps["comp"].get(comp_date, []):
            comp_changes.append(
                {
                    "date": comp_date,
                    "from": from_maps["comp"].get(comp_date, []),
                    "to": to_maps["comp"].get(comp_date, []),
                }
            )

    capacity_changes = []
    for comp_date in sorted(set(from_maps["capacities"]) | set(to_maps["capacities"])):
        if from_maps["capacities"].get(comp_date) != to_maps["capacities"].get(comp_date):
            capacity_changes.append(
                {
                    "date": comp_date,
                    "from": from_maps["capacities"].get(comp_date),
                    "to": to_maps["capacities"].get(comp_date),
                }
            )

    carryover_changes = []
    carryover_keys = set(from_maps["carryovers"]) | set(to_maps["carryovers"])
    for key in sorted(carryover_keys):
        if from_maps["carryovers"].get(key) != to_maps["carryovers"].get(key):
            carryover_changes.append(
                {
                    "employee_id": key[0],
                    "source_holiday_date": key[1],
                    "from": from_maps["carryovers"].get(key),
                    "to": to_maps["carryovers"].get(key),
                }
            )

    return {
        "holiday_changes": holiday_changes,
        "comp_changes": comp_changes,
        "capacity_changes": capacity_changes,
        "carryover_changes": carryover_changes,
    }


def save_review_assignments(
    db: Session,
    schedule_month: ScheduleMonth,
    actor: User,
    version_number: int,
    override_mode: bool,
    holiday_assignments: dict[str, str],
    comp_assignments: dict[str, list[str]],
    capacities: dict[str, int],
    pending_carryovers: list[dict[str, Any]],
) -> dict[str, Any]:
    if schedule_month.status == "locked" and actor.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="鎖定後只有管理者可修改")
    if schedule_month.status not in {"review_open", "locked"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="目前不在可編輯月份階段")
    if (
        schedule_month.status == "review_open"
        and is_review_deadline_expired(schedule_month)
        and actor.role != "admin"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="已超過修改截止時間，只有管理者可修改")
    if schedule_month.latest_version_number != version_number:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="版本已過期，請重新載入最新資料")
    if override_mode and actor.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有管理者可使用覆寫模式")

    participants = list_participants(db, schedule_month.id)
    participant_ids = {item.user_id for item in participants}
    holiday_dates = sorted(
        [item.date for item in db.scalars(select(HolidayDate).where(HolidayDate.schedule_month_id == schedule_month.id)).all()]
    )
    capacity_records = {item.date: item for item in list_capacities(db, schedule_month.id)}
    all_comp_dates = set(capacity_records.keys())

    if sorted(holiday_assignments.keys()) != holiday_dates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="值班日期集合不完整")

    for duty_date, employee_id in holiday_assignments.items():
        if employee_id not in participant_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{duty_date} 指派到非參與者")

    normalized_capacities = {date_key: capacity_records[date_key].capacity for date_key in all_comp_dates}
    for date_key, capacity in capacities.items():
        if date_key not in all_comp_dates:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="包含未知的補休日容量設定")
        if capacity < 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="補休日容量不可小於 0")
        normalized_capacities[date_key] = capacity

    comp_by_user: dict[str, list[str]] = defaultdict(list)
    for comp_date, employee_ids in comp_assignments.items():
        if comp_date not in all_comp_dates:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="包含未知的補休日")
        if len(employee_ids) != len(set(employee_ids)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="同一補休日不可重複安排同一人")
        if len(employee_ids) > normalized_capacities[comp_date]:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{comp_date} 超出補休日容量")
        for employee_id in employee_ids:
            if employee_id not in participant_ids:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="補休日包含非參與者")
            comp_by_user[employee_id].append(comp_date)

    carryover_by_user: dict[str, list[str]] = defaultdict(list)
    for item in pending_carryovers:
        employee_id = item["employee_id"]
        source_holiday_date = item["source_holiday_date"]
        if employee_id not in participant_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="跨月待處理包含非參與者")
        if source_holiday_date not in holiday_dates:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="跨月待處理來源值班日不合法")
        carryover_by_user[employee_id].append(source_holiday_date)

    holiday_by_user: dict[str, list[str]] = defaultdict(list)
    for duty_date, employee_id in holiday_assignments.items():
        holiday_by_user[employee_id].append(duty_date)

    participant_map = {item.user_id: item for item in participants}
    for user_id in participant_ids:
        ordered_holidays = sorted_date_list(holiday_by_user[user_id])
        ordered_comp_dates = sorted_date_list(comp_by_user[user_id])
        user_carryovers = carryover_by_user[user_id]
        if not set(user_carryovers).issubset(set(ordered_holidays)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="跨月待處理來源值班日必須屬於該員工",
            )
        validate_pick_dates(ordered_holidays, ordered_comp_dates, len(user_carryovers))
        if not override_mode:
            if len(ordered_holidays) != participant_map[user_id].holiday_quota:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="值班天數與 quota 不符")
            if len(ordered_comp_dates) + len(user_carryovers) != participant_map[user_id].comp_quota:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="補休天數與 quota 不符")

    before_snapshot = create_snapshot(db, schedule_month)

    db.execute(delete(Assignment).where(Assignment.schedule_month_id == schedule_month.id))
    db.execute(delete(PendingCarryover).where(PendingCarryover.schedule_month_id == schedule_month.id))

    for date_key, capacity in normalized_capacities.items():
        capacity_records[date_key].capacity = capacity

    for duty_date, employee_id in holiday_assignments.items():
        db.add(
            Assignment(
                schedule_month_id=schedule_month.id,
                user_id=employee_id,
                date=duty_date,
                assignment_type="holiday_duty",
            )
        )

    for comp_date, employee_ids in comp_assignments.items():
        for employee_id in employee_ids:
            db.add(
                Assignment(
                    schedule_month_id=schedule_month.id,
                    user_id=employee_id,
                    date=comp_date,
                    assignment_type="comp_day_off",
                )
            )

    for item in pending_carryovers:
        db.add(
            PendingCarryover(
                schedule_month_id=schedule_month.id,
                user_id=item["employee_id"],
                source_holiday_date=item["source_holiday_date"],
                requested_target_month=item.get("requested_target_month"),
                created_by=actor.employee_id,
            )
        )

    version = create_version(db, schedule_month, actor.employee_id, "review_save")
    after_snapshot = version.snapshot
    log_action(
        db,
        actor.employee_id,
        "save_assignments_override" if override_mode else "save_assignments",
        schedule_month.id,
        schedule_month.year,
        schedule_month.month,
        before_snapshot,
        after_snapshot,
        sorted(participant_ids),
        commit=False,
    )
    db.commit()

    return {
        "latest_version_number": version.version_number,
        "version_name": version.version_name,
    }
