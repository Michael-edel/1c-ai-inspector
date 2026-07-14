from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import Base, TrafficUsage
from app.services.traffic import (
    TrafficController,
    TrafficLimitExceeded,
    traffic_period,
    traffic_snapshot,
)


def _settings():
    return get_settings().model_copy(
        update={
            "traffic_warning_bytes": 5_000_000,
            "traffic_critical_bytes": 8_000_000,
            "traffic_hard_limit_bytes": 9_800_000,
        }
    )


def test_traffic_controller_reserves_then_records_actual_bytes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    controller = TrafficController(factory, _settings())

    reservation = controller.reserve(1_000_000)
    with Session(engine) as db:
        reserved = traffic_snapshot(db, _settings())
        assert reserved["usedBytes"] == 0
        assert reserved["reservedBytes"] == 1_000_000

    controller.finalize(reservation, 240_000)
    with Session(engine) as db:
        snapshot = traffic_snapshot(db, _settings())
        assert snapshot["usedBytes"] == 240_000
        assert snapshot["reservedBytes"] == 0
        assert snapshot["level"] == "normal"


def test_traffic_controller_stops_before_hard_limit() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = _settings()
    with Session(engine) as db, db.begin():
        db.add(TrafficUsage(period=traffic_period(), used_bytes=9_000_000, reserved_bytes=0))

    controller = TrafficController(factory, settings)
    try:
        controller.reserve(1_000_000)
    except TrafficLimitExceeded as exc:
        assert str(exc) == "MONTHLY_TRAFFIC_LIMIT_EXCEEDED"
    else:
        raise AssertionError("traffic over the hard limit must be rejected")


def test_traffic_snapshot_exposes_warning_and_critical_levels() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = _settings()
    with Session(engine) as db, db.begin():
        db.add(TrafficUsage(period=traffic_period(), used_bytes=5_100_000, reserved_bytes=0))
    with Session(engine) as db:
        assert traffic_snapshot(db, settings)["level"] == "warning"
        row = db.get(TrafficUsage, traffic_period())
        assert row is not None
        row.used_bytes = 8_100_000
        db.commit()
        assert traffic_snapshot(db, settings)["level"] == "critical"
