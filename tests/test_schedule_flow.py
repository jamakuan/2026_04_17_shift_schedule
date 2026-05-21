from __future__ import annotations

from collections import defaultdict

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


def test_full_schedule_flow() -> None:
    year = 2099
    month = 1
    reset_month(year, month)

    with TestClient(app) as client:
        login = client.post("/login", json={"employee_id": "2196"})
        assert login.status_code == 200
        token = login.json()["token"]
        headers = {"X-Session-Token": token}

        month_payload = complete_initial_picks(client, headers, year, month)
        assert month_payload["latest_version_number"] == 1
        assert month_payload["current_picker_id"] is None

        open_review = client.post(f"/months/{year}/{month}/review-window/open", json={}, headers=headers)
        assert open_review.status_code == 200
        assert open_review.json()["status"] == "review_open"

        refreshed_month = client.get(f"/months/{year}/{month}", headers=headers).json()
        holiday_assignments = refreshed_month["assignments"]["holiday"]
        comp_assignments = defaultdict(list, refreshed_month["assignments"]["comp"])
        capacities = {item["date"]: item["capacity"] for item in refreshed_month["comp_dates"]}
        pending_carryovers = [
            {
                "employee_id": item["employee_id"],
                "source_holiday_date": item["source_holiday_date"],
                "requested_target_month": item["requested_target_month"],
            }
            for item in refreshed_month["carryovers"]
        ]

        save_response = client.post(
            f"/months/{year}/{month}/assignments/save",
            json={
                "version_number": refreshed_month["latest_version_number"],
                "override_mode": False,
                "holiday_assignments": holiday_assignments,
                "comp_assignments": comp_assignments,
                "capacities": capacities,
                "pending_carryovers": pending_carryovers,
            },
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
