from datetime import date, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.services import finance
from app.services import savings as S
from tests.conftest import add_prod

CFG = get_settings()
START = date(2026, 1, 1)
ASSUME = "Scrap cost uses standard material and conversion cost with 10% salvage; volume comparable."


def build(tiny, base_rate=0.04, post_rate=0.02, base_days=35, post_days=34, post_units=1000, seed=3):
    """One 8-hour record per day: `base_days` baseline days then `post_days` post days, with small deterministic noise."""
    sf = tiny()
    rng = np.random.default_rng(seed)
    with sf() as db:
        for d in range(base_days + post_days):
            rate = base_rate if d < base_days else post_rate
            units = 1000 if d < base_days else post_units
            defective = int(rng.binomial(units, rate))
            add_prod(db, start=datetime.combine(START + timedelta(days=d), datetime.min.time()).replace(hour=6), units=units, defective=defective, target=units)
        db.commit()
    return sf, START + timedelta(days=base_days)


def initiative(sf, intervention, **kw):
    base = dict(title="Fix die alignment", category="quality", scope_type="machine", scope_id=1, value_source="computed", baseline_start=START,
                baseline_end=intervention - timedelta(days=1), intervention_date=intervention, post_start=intervention, post_end=intervention + timedelta(days=33),
                expected_savings=50000, assumptions=ASSUME)
    base.update(kw)
    return m.SavingsInitiative(**base)


def run(sf, init):
    with sf() as db:
        db.add(init)
        db.flush()
        res = S.evaluate(db, init)
        db.commit()
        return init, res


def test_genuine_improvement_with_evidence_is_verified(tiny):
    sf, iv = build(tiny)
    init, res = run(sf, initiative(sf, iv))
    assert res["status"] == "verified" and all(c["passed"] for c in res["checks"])
    expected = finance.savings_from_rates(res["baseline_rate"], res["post_rate"], res["post_volume"])
    assert init.calculated_savings == finance.money(expected) > 0
    assert "not a controlled experiment" in res["caveat"]


def test_savings_equal_rate_difference_times_post_volume(tiny):
    sf, iv = build(tiny)
    _, res = run(sf, initiative(sf, iv))
    # 1000 units/day x 34 days, scrap cost 42 x 0.9 per defective unit; ~2 pp improvement
    assert res["post_volume"] == 34000
    assert res["calculated_savings"] == pytest.approx(34000 * 0.02 * 42 * 0.9, rel=0.2)


def test_no_real_improvement_is_not_verified(tiny):
    sf, iv = build(tiny, post_rate=0.04)
    _, res = run(sf, initiative(sf, iv))
    assert res["status"] == "estimated"
    failed = {c["name"] for c in res["checks"] if not c["passed"]}
    assert "Material improvement" in failed and "Change distinguishable from noise" in failed
    assert "estimate, not proven causal" in res["caveat"]


def test_short_baseline_blocks_verification(tiny):
    sf, iv = build(tiny)
    init = initiative(sf, iv, baseline_start=iv - timedelta(days=7))
    _, res = run(sf, init)
    assert res["status"] == "estimated"
    assert not next(c for c in res["checks"] if c["name"] == "Baseline long enough")["passed"]


def test_volume_change_blocks_verification(tiny):
    sf, iv = build(tiny, post_units=1700)
    _, res = run(sf, initiative(sf, iv))
    assert res["status"] == "estimated"
    assert not next(c for c in res["checks"] if c["name"] == "Comparable volume")["passed"]


def test_missing_assumptions_blocks_verification(tiny):
    sf, iv = build(tiny)
    _, res = run(sf, initiative(sf, iv, assumptions=""))
    assert res["status"] == "estimated"


def test_overlapping_periods_blocked(tiny):
    sf, iv = build(tiny)
    _, res = run(sf, initiative(sf, iv, baseline_end=iv + timedelta(days=3)))
    assert res["status"] == "estimated"
    assert not next(c for c in res["checks"] if c["name"] == "Periods ordered")["passed"]


def test_manual_positive_numbers_are_never_verified(tiny):
    sf, iv = build(tiny)
    init, res = run(sf, initiative(sf, iv, value_source="manual", baseline_value=100.0, post_value=1.0, manual_volume=1_000_000))
    assert res["status"] == "estimated" and init.calculated_savings == finance.money(99 * 1_000_000)
    assert "Values computed from loaded data" in {c["name"] for c in res["checks"] if not c["passed"]}


def test_future_intervention_is_forecast(tiny):
    sf, _ = build(tiny)
    future = START + timedelta(days=200)
    _, res = run(sf, initiative(sf, future, baseline_end=future - timedelta(days=1), post_end=future + timedelta(days=20)))
    assert res["status"] == "forecast" and res["calculated_savings"] is None


def test_no_periods_is_opportunity_or_forecast(tiny):
    sf, _ = build(tiny)
    _, res = run(sf, m.SavingsInitiative(title="Idea", category="downtime", scope_type="factory", expected_savings=0, assumptions=""))
    assert res["status"] == "identified"
    _, res = run(sf, m.SavingsInitiative(title="Idea 2", category="downtime", scope_type="factory", expected_savings=100000, assumptions=""))
    assert res["status"] == "forecast"


def test_welch_t_needs_enough_days():
    assert S.welch_t([1, 2, 3], [4, 5, 6]) is None
    assert S.welch_t([1.0] * 10, [1.0] * 10) is None  # zero variance
    assert S.welch_t(list(np.arange(10.0)), list(np.arange(10.0) + 10)) < -2


# ----------------------------------------------------------------------------- via the API
def test_api_cannot_force_verified_status(client):
    r = client.post("/api/savings", json=dict(title="Trust me", category="quality", evidence_status="verified", calculated_savings=9e9, expected_savings=1000))
    assert r.status_code == 201
    body = r.json()
    assert body["evidence_status"] == "forecast" and body["calculated_savings"] is None


def test_api_create_update_and_evaluate_on_demo_data(client):
    cfg = client.get("/api/config").json()
    end = date.fromisoformat(cfg["data_to"])
    iv = end - timedelta(days=30)
    r = client.post("/api/savings", json=dict(
        title="Reduce B2 downtime", category="downtime", scope_type="machine", scope_id=5, baseline_start=str(iv - timedelta(days=35)), baseline_end=str(iv - timedelta(days=1)),
        intervention_date=str(iv), post_start=str(iv), post_end=str(end), expected_savings=250000, assumptions="Margin-based downtime cost model, 70% unrecoverable."))
    assert r.status_code == 201
    body = r.json()
    assert body["evidence_status"] in ("estimated", "verified") and body["evidence"]["checks"]
    sid = body["id"]
    patched = client.patch(f"/api/savings/{sid}", json={"notes": "Bearing kit replaced", "assumptions": ""}).json()
    assert patched["notes"] == "Bearing kit replaced" and patched["evidence_status"] != "verified"
    assert client.post(f"/api/savings/{sid}/evaluate").status_code == 200
    listing = client.get("/api/savings").json()
    assert any(i["id"] == sid for i in listing["items"])
    assert client.delete(f"/api/savings/{sid}").status_code == 204
    assert client.get(f"/api/savings/{sid}").status_code == 404


def test_api_savings_validation(client):
    ok = dict(title="Valid title", category="quality")
    assert client.post("/api/savings", json={**ok, "category": "morale"}).status_code == 422
    assert client.post("/api/savings", json={**ok, "title": "x"}).status_code == 422
    assert client.post("/api/savings", json={**ok, "expected_savings": -5}).status_code == 422
    assert client.post("/api/savings", json={**ok, "baseline_start": "2026-02-01", "baseline_end": "2026-01-01"}).status_code == 422
    assert client.post("/api/savings", json={**ok, "scope_type": "machine"}).status_code == 422
    assert client.post("/api/savings", json={**ok, "scope_type": "machine", "scope_id": 9999}).status_code == 422
    assert client.patch("/api/savings/9999", json={"notes": "x"}).status_code == 404
