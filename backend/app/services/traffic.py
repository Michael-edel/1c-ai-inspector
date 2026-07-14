from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import TrafficUsage


class TrafficLimitExceeded(RuntimeError):
    """Raised before an external call that cannot fit inside the monthly budget."""


@dataclass(frozen=True)
class TrafficReservation:
    period: str
    bytes: int


def traffic_period(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m")


def traffic_level(used_bytes: int, settings: Settings) -> str:
    if used_bytes >= getattr(settings, "traffic_hard_limit_bytes", 9_800_000_000):
        return "blocked"
    if used_bytes >= getattr(settings, "traffic_critical_bytes", 8_000_000_000):
        return "critical"
    if used_bytes >= getattr(settings, "traffic_warning_bytes", 5_000_000_000):
        return "warning"
    return "normal"


def traffic_snapshot(db: Session, settings: Settings) -> dict[str, int | str]:
    period = traffic_period()
    row = db.get(TrafficUsage, period)
    used = int(row.used_bytes) if row is not None else 0
    reserved = int(row.reserved_bytes) if row is not None else 0
    accounted = used + reserved
    warning = getattr(settings, "traffic_warning_bytes", 5_000_000_000)
    critical = getattr(settings, "traffic_critical_bytes", 8_000_000_000)
    hard_limit = getattr(settings, "traffic_hard_limit_bytes", 9_800_000_000)
    return {
        "period": period,
        "usedBytes": used,
        "reservedBytes": reserved,
        "accountedBytes": accounted,
        "remainingBytes": max(0, hard_limit - accounted),
        "warningBytes": warning,
        "criticalBytes": critical,
        "hardLimitBytes": hard_limit,
        "level": traffic_level(accounted, settings),
        "maxTaskBytes": (
            getattr(settings, "max_task_mcp_bytes", 12_000_000)
            + getattr(settings, "max_model_response_bytes", 2_000_000)
            + getattr(settings, "max_context_chars", 120_000) * 4
            + 1_000_000
        ),
    }


class TrafficController:
    def __init__(self, factory: sessionmaker[Session], settings: Settings):
        self.factory = factory
        self.settings = settings

    def reserve(self, maximum_bytes: int) -> TrafficReservation:
        if maximum_bytes <= 0:
            raise ValueError("traffic reservation must be positive")
        period = traffic_period()
        with self.factory() as db, db.begin():
            row = db.scalar(
                select(TrafficUsage).where(TrafficUsage.period == period).with_for_update()
            )
            if row is None:
                row = TrafficUsage(period=period, used_bytes=0, reserved_bytes=0)
                db.add(row)
                db.flush()
            if row.used_bytes + row.reserved_bytes + maximum_bytes > self.settings.traffic_hard_limit_bytes:
                raise TrafficLimitExceeded("MONTHLY_TRAFFIC_LIMIT_EXCEEDED")
            row.reserved_bytes += maximum_bytes
        return TrafficReservation(period=period, bytes=maximum_bytes)

    def finalize(self, reservation: TrafficReservation, actual_bytes: int) -> None:
        if actual_bytes < 0 or actual_bytes > reservation.bytes:
            raise ValueError("actual traffic is outside the reserved range")
        with self.factory() as db, db.begin():
            row = db.scalar(
                select(TrafficUsage)
                .where(TrafficUsage.period == reservation.period)
                .with_for_update()
            )
            if row is None or row.reserved_bytes < reservation.bytes:
                raise RuntimeError("TRAFFIC_RESERVATION_NOT_FOUND")
            row.reserved_bytes -= reservation.bytes
            row.used_bytes += actual_bytes

    def release(self, reservation: TrafficReservation) -> None:
        self.finalize(reservation, 0)
