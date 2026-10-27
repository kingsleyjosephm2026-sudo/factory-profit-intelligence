from datetime import date

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import models as m
from app.database import Base, make_engine
from app.services import analytics as A
from app.services import datagen
from tests.conftest import END


def _fresh(days, seed):
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    sf = sessionmaker(bind=eng)
    with sf() as db:
        datagen.generate_history(db, days, END, seed)
    return sf


def test_dataset_shape_matches_brief(db):
    assert db.scalar(select(func.count()).select_from(m.ProductionLine)) == 3
    assert db.scalar(select(func.count()).select_from(m.Machine)) == 10
    assert db.scalar(select(func.count()).select_from(m.Product)) >= 6
    assert set(db.scalars(select(m.ProductionRecord.shift).distinct())) == {"A", "B", "C"}
    lo, hi = A.data_bounds(db)
    assert (hi - lo).days + 1 == 90
    assert db.scalar(select(func.count()).select_from(m.DowntimeEvent)) > 1000
    assert db.scalar(select(func.count()).select_from(m.InventorySnapshot)) > 300
    assert db.scalar(select(func.count(func.distinct(m.DowntimeEvent.reason_code)))) >= 8


def test_fixed_seed_is_reproducible():
    def fingerprint(sf):
        with sf() as db:
            return (db.scalar(select(func.sum(m.ProductionRecord.units_produced))), db.scalar(select(func.sum(m.ProductionRecord.defective_units))),
                    db.scalar(select(func.count()).select_from(m.DowntimeEvent)), round(db.scalar(select(func.sum(m.EnergyRecord.kwh))), 3))
    assert fingerprint(_fresh(20, 42)) == fingerprint(_fresh(20, 42))
    assert fingerprint(_fresh(20, 42)) != fingerprint(_fresh(20, 7))


def test_records_are_internally_coherent(db):
    P = pd.read_sql(select(m.ProductionRecord), db.connection())
    assert (P.units_produced >= P.defective_units).all()
    assert (P.planned_downtime_min + P.unplanned_downtime_min <= P.period_minutes + 1e-6).all()
    # defect categories add up to the defective units of each record
    q = pd.read_sql(select(m.QualityRecord.production_record_id, m.QualityRecord.defective_units), db.connection()).groupby("production_record_id").defective_units.sum()
    with_defects = P.set_index("id").defective_units
    with_defects = with_defects[with_defects > 0]
    assert (q.reindex(with_defects.index) == with_defects).all()
    # every production record has an energy record and vice versa
    E = pd.read_sql(select(m.EnergyRecord), db.connection())
    assert len(E) == len(P)


def test_unplanned_events_sum_to_record_downtime(db):
    P = pd.read_sql(select(m.ProductionRecord), db.connection())
    E = pd.read_sql(select(m.DowntimeEvent), db.connection())
    P["period_start"], E["start_ts"] = pd.to_datetime(P.period_start), pd.to_datetime(E.start_ts)
    E = E.sort_values("start_ts")
    P = P.sort_values("period_start")
    Pr = P[["machine_id", "period_start", "id"]].rename(columns={"id": "record_id"})
    j = pd.merge_asof(E, Pr, left_on="start_ts", right_on="period_start", by="machine_id")
    got = j[~j.planned.astype(bool)].groupby("record_id").duration_min.sum()
    want = P.set_index("id").unplanned_downtime_min
    got = got.reindex(want.index).fillna(0)
    assert (got - want).abs().max() < 0.15  # rounding to 0.1 min per event


def test_planted_patterns_exist_for_analytics_to_find(db):
    f = A.default_filters(db, days=90)
    df = A.load_frame(db, f)
    a = A.aggregate(df, ["machine_code"]).set_index("machine_code")
    assert a.loc["M-B2", "unplanned_downtime_pct"] > 2 * a.unplanned_downtime_pct.median()
    lc = A.aggregate(df[df.line_code == "LC"], ["shift"]).set_index("shift")
    assert lc.loc["C", "defect_rate_pct"] > 1.2 * lc.loc[["A", "B"], "defect_rate_pct"].mean()


def test_inventory_never_negative_and_replenishes(db):
    inv = pd.read_sql(select(m.InventorySnapshot), db.connection())
    assert (inv.quantity_on_hand >= 0).all()
    steel = inv[inv.item_code == "RM-STL"].sort_values("snapshot_date")
    assert (steel.quantity_on_hand.diff() > 0).any()  # deliveries happened
