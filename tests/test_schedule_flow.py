from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.models import (
    Assignment,
    AuditLog,
    CompOffCapacity,
    HolidayDate,
    MonthParticipant,
    PendingCarryover,
    ScheduleMonth,
    ScheduleVersion,
)
from app.db.session import SessionLocal
from app.main import app


def reset_month(year: int, month: int) -> None:
    with SessionLocal() as session:
        schedule_month = session.scalar(
            select(ScheduleMonth).where(
                ScheduleMonth.year == year,
                ScheduleMonth.month == month,
            )
        )
        if schedule_month is None:
            return

        session.execute(delete(Assignment).where(Assignment.schedule_month_id == schedule_month.id))
        session.execute(delete(PendingCarryover).where(PendingCarryover.schedule_month_id == schedule_month.id))
        session.execute(delete(CompOffCapacity).where(CompOffCapacity.schedule_month_id == schedule_month.id))
        session.execute(delete(HolidayDate).where(HolidayDate.schedule_month_id == schedule_month.id))
        session.execute(delete(MonthParticipant).where(MonthParticipant.schedule_month_id == schedule_month.id))
        session.execute(delete(ScheduleVersion).where(ScheduleVersion.schedule_month_id == schedule_month.id))
        session.execute(delete(AuditLog).where(AuditLog.schedule_month_id == schedule_month.id))
        session.delete(schedule_month)
        session.commit()


def login_headers(client: TestClient, employee_id: str) -> dict[str, str]:
    response = client.post("/login", json={"employee_id": employee_id})
    assert response.status_code == 200
    return {"X-Session-Token": response.json()["token"]}


def complete_initial_picks(client: TestClient, headers: dict[str, str], year: int, month: int) -> dict:
    payload = client.post(f"/months/{year}/{month}/start-picking", json={}, headers=headers).json()
    participants = payload["participants"]
    holiday_dates = [item["date"] for item in payload["holiday_dates"]]
    comp_dates = [item["date"] for item in payload["comp_dates"]]
    cursor_holiday = 0
    used_comp_dates: set[str] = set()

    for participant in participants:
        quota = participant["holiday_quota"]
        picked_holidays = holiday_dates[cursor_holiday : cursor_holiday + quota]
        picked_comp_dates = []
        carryover_count = 0
        available_comp_dates = [item for item in comp_dates if item not in used_comp_dates]

        for holiday_date in picked_holidays:
            valid_comp_date = next(
                (item for item in available_comp_dates if item > holiday_date and item not in picked_comp_dates),
                None,
            )
            if valid_comp_date is None:
                carryover_count += 1
            else:
                picked_comp_dates.append(valid_comp_date)
                used_comp_dates.add(valid_comp_date)
                available_comp_dates.remove(valid_comp_date)

        cursor_holiday += quota
        response = client.post(
            f"/months/{year}/{month}/picks/submit",
            json={
                "employee_id": participant["employee_id"],
                "holiday_dates": picked_holidays,
                "comp_dates": picked_comp_dates,
                "carryover_count": carryover_count,
            },
            headers=headers,
        )
        assert response.status_code == 200

    return client.get(f"/months/{year}/{month}", headers=headers).json()


def build_save_payload(month_payload: dict) -> dict:
    return {
        "version_number": month_payload["latest_version_number"],
        "override_mode": False,
        "holiday_assignments": month_payload["assignments"]["holiday"],
        "comp_assignments": {
            date_key: list(employee_ids)
            for date_key, employee_ids in month_payload["assignments"]["comp"].items()
        },
        "capacities": {item["date"]: item["capacity"] for item in month_payload["comp_dates"]},
        "pending_carryovers": [
            {
                "employee_id": item["employee_id"],
                "source_holiday_date": item["source_holiday_date"],
                "requested_target_month": item["requested_target_month"],
            }
            for item in month_payload["carryovers"]
        ],
    }


def test_full_schedule_flow() -> None:
    year = 2099
    month = 1
    reset_month(year, month)

    with TestClient(app) as client:
        headers = login_headers(client, "2196")

        month_payload = complete_initial_picks(client, headers, year, month)
        assert month_payload["latest_version_number"] == 1
        assert month_payload["current_picker_id"] is None

        open_review = client.post(f"/months/{year}/{month}/review-window/open", json={}, headers=headers)
        assert open_review.status_code == 200
        assert open_review.json()["status"] == "review_open"

        refreshed_month = client.get(f"/months/{year}/{month}", headers=headers).json()
        save_response = client.post(
            f"/months/{year}/{month}/assignments/save",
            json=build_save_payload(refreshed_month),
            headers=headers,
        )
        assert save_response.status_code == 200
        assert save_response.json()["latest_version_number"] == 2

        versions = client.get(f"/months/{year}/{month}/versions", headers=headers)
        assert versions.status_code == 200
        version_items = versions.json()["items"]
        assert len(version_items) == 2

        diff = client.get(
            f"/months/{year}/{month}/diff",
            params={"from": version_items[-1]["id"], "to": version_items[0]["id"]},
            headers=headers,
        )
        assert diff.status_code == 200
        diff_payload = diff.json()["diff"]
        assert diff_payload["holiday_changes"] == []
        assert diff_payload["comp_changes"] == []

        logs = client.get("/audit-logs", headers=headers)
        assert logs.status_code == 200
        action_types = [item["action_type"] for item in logs.json()["items"]]
        assert "login" in action_types
        assert "save_assignments" in action_types


def test_review_deadline_blocks_employee_edits_after_expiry() -> None:
    year = 2099
    month = 2
    reset_month(year, month)

    with TestClient(app) as client:
        admin_headers = login_headers(client, "2196")
        employee_headers = login_headers(client, "2138")

        complete_initial_picks(client, admin_headers, year, month)
        past_deadline = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        open_review = client.post(
            f"/months/{year}/{month}/review-window/open",
            json={"review_deadline": past_deadline},
            headers=admin_headers,
        )
        assert open_review.status_code == 200

        employee_month = client.get(f"/months/{year}/{month}", headers=employee_headers)
        assert employee_month.status_code == 200
        employee_payload = employee_month.json()
        assert employee_payload["review_deadline_expired"] is True
        assert employee_payload["permissions"]["can_edit_all"] is False

        employee_save = client.post(
            f"/months/{year}/{month}/assignments/save",
            json=build_save_payload(employee_payload),
            headers=employee_headers,
        )
        assert employee_save.status_code == 403
        assert employee_save.json()["detail"] == "已超過修改截止時間，只有管理者可修改"

        admin_month = client.get(f"/months/{year}/{month}", headers=admin_headers).json()
        admin_save = client.post(
            f"/months/{year}/{month}/assignments/save",
            json=build_save_payload(admin_month),
            headers=admin_headers,
        )
        assert admin_save.status_code == 200


def test_save_rejects_carryover_source_from_other_employee() -> None:
    year = 2099
    month = 10
    reset_month(year, month)

    with TestClient(app) as client:
        headers = login_headers(client, "2196")

        complete_initial_picks(client, headers, year, month)
        open_review = client.post(f"/months/{year}/{month}/review-window/open", json={}, headers=headers)
        assert open_review.status_code == 200

        month_payload = client.get(f"/months/{year}/{month}", headers=headers).json()
        payload = build_save_payload(month_payload)
        target_participant = next(
            item
            for item in month_payload["participants"]
            if item["employee_id"] == "2196"
        )
        payload["comp_assignments"] = dict(payload["comp_assignments"])
        removed_comp_date = target_participant["comp_dates"][0]
        payload["comp_assignments"][removed_comp_date] = [
            employee_id
            for employee_id in payload["comp_assignments"][removed_comp_date]
            if employee_id != target_participant["employee_id"]
        ]
        if not payload["comp_assignments"][removed_comp_date]:
            payload["comp_assignments"].pop(removed_comp_date)

        payload["pending_carryovers"].append(
            {
                "employee_id": target_participant["employee_id"],
                "source_holiday_date": "2099-10-17",
                "requested_target_month": None,
            }
        )

        save_response = client.post(
            f"/months/{year}/{month}/assignments/save",
            json=payload,
            headers=headers,
        )
        assert save_response.status_code == 422
        assert save_response.json()["detail"] == "跨月待處理來源值班日必須屬於該員工"


def test_start_picking_rejects_invalid_month() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = login_headers(client, "2196")
        response = client.post("/months/2026/13/start-picking", json={}, headers=headers)

    assert response.status_code == 422
    assert response.json()["detail"] == "月份必須介於 1 到 12"
