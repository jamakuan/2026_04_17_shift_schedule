from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class AppMetadata(Base):
    __tablename__ = "app_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    employee_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="employee", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    holiday_fixed_off: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("users.employee_id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship()


class ScheduleMonth(Base, TimestampMixin):
    __tablename__ = "schedule_months"
    __table_args__ = (UniqueConstraint("year", "month", name="uq_schedule_month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    current_picker_id: Mapped[str | None] = mapped_column(
        String(20),
        ForeignKey("users.employee_id"),
        nullable=True,
    )
    review_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    latest_version_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("users.employee_id"),
        nullable=False,
    )


class MonthParticipant(Base, TimestampMixin):
    __tablename__ = "month_participants"
    __table_args__ = (
        UniqueConstraint("schedule_month_id", "user_id", name="uq_month_participant_user"),
        UniqueConstraint("schedule_month_id", "pick_order", name="uq_month_participant_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_month_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("schedule_months.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("users.employee_id"),
        nullable=False,
    )
    pick_order: Mapped[int] = mapped_column(Integer, nullable=False)
    holiday_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    comp_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    has_completed_initial_pick: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship()


class HolidayDate(Base):
    __tablename__ = "holiday_dates"
    __table_args__ = (UniqueConstraint("schedule_month_id", "date", name="uq_holiday_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_month_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("schedule_months.id"),
        nullable=False,
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_national_holiday: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_saturday: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CompOffCapacity(Base):
    __tablename__ = "comp_off_capacities"
    __table_args__ = (UniqueConstraint("schedule_month_id", "date", name="uq_comp_capacity_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_month_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("schedule_months.id"),
        nullable=False,
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Assignment(Base, TimestampMixin):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint(
            "schedule_month_id",
            "user_id",
            "date",
            "assignment_type",
            name="uq_assignment_entry",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_month_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("schedule_months.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("users.employee_id"),
        nullable=False,
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    assignment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_holiday_date: Mapped[str | None] = mapped_column(String(10), nullable=True)

    user: Mapped[User] = relationship()


class PendingCarryover(Base):
    __tablename__ = "pending_carryovers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_month_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("schedule_months.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("users.employee_id"),
        nullable=False,
    )
    source_holiday_date: Mapped[str] = mapped_column(String(10), nullable=False)
    requested_target_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("users.employee_id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class ScheduleVersion(Base):
    __tablename__ = "schedule_versions"
    __table_args__ = (
        UniqueConstraint("schedule_month_id", "version_number", name="uq_schedule_version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_month_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("schedule_months.id"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("users.employee_id"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    user: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(
        String(20),
        ForeignKey("users.employee_id"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    schedule_month_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("schedule_months.id"),
        nullable=True,
    )
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    before_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    affected_users: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    actor: Mapped[User | None] = relationship()
