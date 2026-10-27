"""Shared fixtures. All tests use in-memory SQLite and the fixed-seed demo dataset (never the dev database)."""
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("FPI_DATABASE_URL", "sqlite://")

from app import models as m  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import Base, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import datagen  # noqa: E402

END = date(2026, 10, 24)


@pytest.fixture(scope="session")
def template_bytes() -> bytes:
    """A serialized 90-day demo database, generated once, cloned cheaply per test."""
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as db:
        datagen.generate_history(db, 90, END, 42)
    raw = eng.raw_connection()
    data = raw.driver_connection.serialize()
    raw.close()
    return data


def clone(data: bytes | None):
    eng = make_engine("sqlite://")
    if data is None:
        Base.metadata.create_all(eng)
    else:
        raw = eng.raw_connection()
        raw.driver_connection.deserialize(data)
        raw.close()
    return eng


@pytest.fixture()
def engine(template_bytes):
    eng = clone(template_bytes)
    yield eng
    eng.dispose()


@pytest.fixture()
def SessionF(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db(SessionF):
    with SessionF() as s:
        yield s


@pytest.fixture()
def client(SessionF):
    app = create_app(SessionF)
    return TestClient(app)


@pytest.fixture()
def empty_client():
    eng = clone(None)
    sf = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    yield TestClient(create_app(sf))
    eng.dispose()


@pytest.fixture()
def tiny():
    """Factory for a minimal DB with reference data and hand-built records (so expectations can be computed by hand)."""
    made = []

    def build():
        eng = clone(None)
        sf = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
        with sf() as s:
            datagen.create_reference(s)
            s.commit()
        made.append(eng)
        return sf

    yield build
    for e in made:
        e.dispose()


def add_prod(db, machine="M-A1", sku="P-A01", start=datetime(2026, 3, 1, 6), minutes=480, planned=0.0, unpl=0.0, units=1000, defective=0, target=1000,
             material=0.0, kwh=None, tariff=7.5, shift="A"):
    from sqlalchemy import select
    mc = db.scalar(select(m.Machine).where(m.Machine.code == machine))
    pr = db.scalar(select(m.Product).where(m.Product.sku == sku))
    rec = m.ProductionRecord(machine_id=mc.id, product_id=pr.id, period_start=start, period_minutes=minutes, shift=shift, planned_downtime_min=planned,
                             unplanned_downtime_min=unpl, units_produced=units, defective_units=defective, target_units=target, material_cost=material,
                             labor_hours=16, labor_cost=3680, source="demo")
    db.add(rec)
    if kwh is not None:
        db.add(m.EnergyRecord(machine_id=mc.id, period_start=start, kwh=kwh, tariff=tariff, source="demo"))
    db.flush()
    return rec
