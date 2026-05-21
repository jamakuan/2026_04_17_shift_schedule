from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    employee_id: str


class LoginResponse(BaseModel):
    token: str
    session_header: str
    user: dict


class StartPickingRequest(BaseModel):
    review_deadline: datetime | None = None


class SubmitPickRequest(BaseModel):
    employee_id: str | None = None
    holiday_dates: list[str] = Field(default_factory=list)
    comp_dates: list[str] = Field(default_factory=list)
    carryover_count: int = 0


class ReviewWindowRequest(BaseModel):
    review_deadline: datetime | None = None


class PendingCarryoverInput(BaseModel):
    employee_id: str
    source_holiday_date: str
    requested_target_month: str | None = None


class SaveAssignmentsRequest(BaseModel):
    version_number: int
    override_mode: bool = False
    holiday_assignments: dict[str, str]
    comp_assignments: dict[str, list[str]]
    capacities: dict[str, int] = Field(default_factory=dict)
    pending_carryovers: list[PendingCarryoverInput] = Field(default_factory=list)
