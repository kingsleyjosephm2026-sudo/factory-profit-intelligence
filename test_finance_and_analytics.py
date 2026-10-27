from datetime import date, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.services import analytics as A
from app.services import finance
from tests.conftest import add_prod

CFG = get_settings()


# ----------------------------------------------------------------------------- finance
def test_money_rounds_half_up_with_decimal():
    assert finance.money(2.675) == 2.68  # float arithmetic would give 2.67
    assert finance.money(None) == 0.0
    assert finance.money(float("nan")) == 0.0


def test_safe_div_zero_denominator():
    assert finance.safe_div(5, 0) is None
    assert finance.safe_div(1, 4) == 0.25


def test_vectorised_losses_match_decimal_reference(db):
    f = A.default_filters(db)
    df = A.load_frame(db, f, CFG)
    sample = df.sample(60, random_state=1)
    for _, r in sample.iterrows():
        ref = finance.record_losses(r.to_dict(), CFG, None if np.isnan(r.base_kwh_unit) or not r.has_energy else r.base_kwh_unit)
        assert float(ref["downtime"]) == pytest.approx(r.loss_downtime, abs=0.01)
        assert float(ref["quality"]) == pytest.approx(r.loss_quality, abs=0.01)
        assert float(ref["energy"]) == pytest.approx(r.loss_energy, abs=0.01)
        assert float(ref["material"]) == pytest.approx(r.loss_material, abs=0.01)


def test_no_double_counting_and_ordering(db):
    f = A.default_filters(db)
    ls = A.loss_summary(db, f)
    cats = {c["category"]: c for c in ls["categories"]}
    assert set(cats) == {"downtime", "quality", "energy", "material", "inventory"}
    assert ls["totals"]["observed"] == pytest.approx(sum(c["observed"] for c in ls["categories"]), abs=0.05)
    for c in ls["categories"]:
        assert c["observed"] >= c["avoidable"] >= c["potential"] >= 0
    assert ls["totals"]["potential"] < ls["totals"]["observed"]  # never present the whole loss as recoverable


def test_downtime_impact_uses_margin_not_revenue(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, unpl=60, units=1000)  # M-A1: 240/h x P-A01 speed 1.0 => 240 lost units; CM = 85-28-14 = 43
        db.commit()
        df = A.load_frame(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)), CFG)
    expected = 240 * 43 * CFG.downtime_unrecoverable_share
    assert df.loss_downtime.iloc[0] == pytest.approx(expected)
    assert df.loss_downtime.iloc[0] < 240 * 85  # strictly less than lost revenue


def test_quality_cost_is_input_cost_not_lost_sale(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, units=1000, defective=100)
        db.commit()
        df = A.load_frame(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)), CFG)
    assert df.loss_quality.iloc[0] == pytest.approx(100 * (28 + 14) * (1 - CFG.scrap_salvage_rate))


# ----------------------------------------------------------------------------- production / quality maths
def test_defect_rate_is_volume_weighted(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, start=datetime(2026, 3, 1, 6), units=1000, defective=20)
        add_prod(db, start=datetime(2026, 3, 1, 14), units=500, defective=5, shift="B")
        db.commit()
        cards = {c["key"]: c for c in A.summary_cards(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)))["cards"]}
    assert cards["defect"]["value"] == pytest.approx(25 / 1500 * 100, abs=0.01)
    assert cards["good"]["value"] == 1475
    assert cards["units"]["value"] == 1500


def test_zero_production_gives_no_rate_not_zero(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, units=0, defective=0, target=0)
        db.commit()
        cards = {c["key"]: c for c in A.summary_cards(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)))["cards"]}
        q = A.quality_analytics(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)))
    assert cards["defect"]["value"] is None
    assert cards["attainment"]["value"] is None
    assert q["first_pass_yield_pct"] is None


def test_empty_window_and_empty_database_do_not_crash(tiny, db):
    f = A.Filters(date(2020, 1, 1), date(2020, 1, 7))
    s = A.summary_cards(db, f)
    assert s["records"] == 0 and len(s["cards"]) == 8
    for fn in (A.production_analytics, A.downtime_analytics, A.quality_analytics, A.energy_analytics, A.dashboard_charts):
        fn(db, f)
    assert A.loss_summary(db, f)["totals"]["observed"] == 0
    sf = tiny()  # reference data only, no records
    with sf() as empty:
        assert A.data_bounds(empty) == (None, None)
        assert A.summary_cards(empty, A.default_filters(empty))["records"] == 0
        assert A.inventory_status(empty, A.default_filters(empty))["items"] == []


def test_target_attainment(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, units=950, target=1000)
        db.commit()
        cards = {c["key"]: c for c in A.summary_cards(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)))["cards"]}
    assert cards["attainment"]["value"] == 95.0


def test_previous_period_comparison_and_percent_validity(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, start=datetime(2026, 3, 1, 6), units=1000)
        add_prod(db, start=datetime(2026, 3, 2, 6), units=1200)
        db.commit()
        s = A.summary_cards(db, A.Filters(date(2026, 3, 2), date(2026, 3, 2)))
        c = {x["key"]: x for x in s["cards"]}["units"]
        assert (c["value"], c["previous"], c["abs_diff"], c["pct_diff"]) == (1200, 1000, 200, 20.0)
        first = {x["key"]: x for x in A.summary_cards(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)))["cards"]}["units"]
    assert first["previous"] is None and first["pct_diff"] is None  # no previous data -> no invalid percentage


def test_pct_change_not_computed_from_zero():
    assert A._pct_change(10, 0) is None
    assert A._pct_change(None, 5) is None
    assert A._pct_change(5, 10) == -50.0


# ----------------------------------------------------------------------------- downtime
def test_planned_and_unplanned_downtime_are_separate_and_mtbf_mttr_correct(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, planned=30, unpl=60, units=1000)
        mid = db.scalar(select(m.Machine.id).where(m.Machine.code == "M-A1"))
        t0 = datetime(2026, 3, 1, 6)
        db.add(m.DowntimeEvent(machine_id=mid, start_ts=t0, duration_min=30, planned=True, reason_code="CHANGEOVER"))
        for i, d in enumerate((10, 20, 30)):
            db.add(m.DowntimeEvent(machine_id=mid, start_ts=t0 + timedelta(hours=1 + i), duration_min=d, planned=False, reason_code="JAM"))
        db.commit()
        out = A.downtime_analytics(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)))
    assert out["totals"]["unplanned_minutes"] == 60 and out["totals"]["planned_minutes"] == 30
    row = out["by_machine"][0]
    run_hours = (480 - 30 - 60) / 60
    assert row["events"] == 3 and row["mttr_minutes"] == 20.0 and row["mtbf_hours"] == pytest.approx(run_hours / 3, abs=0.01)
    assert [r["reason_code"] for r in out["reasons_unplanned"]] == ["JAM"]
    assert [r["reason_code"] for r in out["reasons_planned"]] == ["CHANGEOVER"]


def test_mtbf_withheld_with_too_few_events(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, unpl=20)
        mid = db.scalar(select(m.Machine.id))
        db.add(m.DowntimeEvent(machine_id=mid, start_ts=datetime(2026, 3, 1, 7), duration_min=20, planned=False, reason_code="JAM"))
        db.commit()
        row = A.downtime_analytics(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)))["by_machine"][0]
    assert row["mtbf_hours"] is None and row["mttr_minutes"] is None


# ----------------------------------------------------------------------------- energy
def test_energy_cost_is_kwh_times_tariff(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, units=1000, kwh=100, tariff=7.5)
        add_prod(db, start=datetime(2026, 3, 1, 14), units=500, kwh=40, tariff=8.4, shift="B")
        db.commit()
        e = A.energy_analytics(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)))
    assert e["totals"]["energy_cost"] == pytest.approx(100 * 7.5 + 40 * 8.4)
    assert e["totals"]["kwh"] == 140
    assert e["totals"]["kwh_per_good_unit"] == pytest.approx(140 / 1500, abs=0.001)


def test_missing_energy_records_do_not_create_phantom_loss(tiny):
    sf = tiny()
    with sf() as db:
        add_prod(db, units=1000, kwh=None)
        db.commit()
        df = A.load_frame(db, A.Filters(date(2026, 3, 1), date(2026, 3, 1)), CFG)
    assert df.loss_energy.iloc[0] == 0 and not df.has_energy.iloc[0]


# ----------------------------------------------------------------------------- filters on the seeded dataset
def test_filters_change_results(db):
    f = A.default_filters(db)
    base = A.aggregate(A.load_frame(db, f), None).iloc[0].units
    shift_a = A.aggregate(A.load_frame(db, A.Filters(f.date_from, f.date_to, shift="A")), None).iloc[0].units
    line_a = A.aggregate(A.load_frame(db, A.Filters(f.date_from, f.date_to, line_id=1)), None).iloc[0].units
    assert 0 < shift_a < base and 0 < line_a < base
    assert shift_a == pytest.approx(base / 3, rel=0.15)


def test_inventory_excluded_from_machine_level_filters(db):
    f = A.default_filters(db)
    with_inv = A.loss_summary(db, f)
    machine_filtered = A.loss_summary(db, A.Filters(f.date_from, f.date_to, machine_id=1))
    inv = next(c for c in machine_filtered["categories"] if c["category"] == "inventory")
    assert inv["observed"] == 0 and machine_filtered["inventory_applicable"] is False
    assert next(c for c in with_inv["categories"] if c["category"] == "inventory")["observed"] > 0


def test_inventory_status_flags(db):
    s = A.inventory_status(db, A.default_filters(db))
    by = {i["item_code"]: i for i in s["items"]}
    assert by["RM-ALY"]["below_reorder"] and by["RM-PCB"]["below_reorder"]
    assert by["RM-CTN"]["slow_moving"]
    assert not by["RM-STL"]["below_reorder"]
    assert s["summary"]["stockout_days"] >= 1
