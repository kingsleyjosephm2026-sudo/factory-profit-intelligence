import pytest
from sqlalchemy import func, select

from app import models as m
from app.services import recommendations as R

REQUIRED = ["title", "evidence", "entity_name", "metric", "severity", "next_action", "confidence", "calculation_method", "status"]


@pytest.fixture()
def refreshed(db):
    R.refresh(db)
    return {(r.rule_id, r.entity_key): r for r in db.scalars(select(m.Recommendation))}


def test_planted_problems_trigger_expected_rules(refreshed):
    keys = set(refreshed)
    assert ("downtime_high", "M-B2") in keys
    assert ("defect_rate_high", "Line C - Assembly & Test|C") in keys
    assert ("energy_excess", "M-A3") in keys
    assert ("inventory_below_reorder", "RM-ALY") in keys
    assert ("inventory_below_reorder", "RM-PCB") in keys
    assert ("inventory_slow_moving", "RM-CTN") in keys


def test_healthy_entities_do_not_trigger(refreshed):
    downtime_machines = {k for r, k in refreshed if r == "downtime_high"}
    assert "M-C1" not in downtime_machines and "M-A1" not in downtime_machines
    assert ("inventory_below_reorder", "RM-STL") not in refreshed


def test_every_recommendation_carries_required_fields(refreshed):
    assert refreshed
    for r in refreshed.values():
        for f in REQUIRED:
            assert getattr(r, f) not in (None, ""), f"{r.rule_id}/{r.entity_key} missing {f}"
        assert r.severity in ("High", "Medium", "Low") and r.status == "Open"
        assert r.last_evaluated_at is not None and r.created_at is not None
        assert r.metric_value is not None and r.threshold is not None


def test_opportunity_is_conservative_and_inventory_claims_none(refreshed):
    b2 = refreshed[("downtime_high", "M-B2")]
    assert 0 < b2.estimated_opportunity
    assert refreshed[("inventory_below_reorder", "RM-ALY")].estimated_opportunity is None  # risk, not cost: nothing claimed


def test_refresh_is_idempotent_and_preserves_user_work(db):
    first = R.refresh(db)
    n = db.scalar(select(func.count()).select_from(m.Recommendation))
    rec = db.scalar(select(m.Recommendation).where(m.Recommendation.rule_id == "downtime_high"))
    rec.status, rec.notes = "In progress", "Bearing replacement booked for Friday"
    db.commit()
    second = R.refresh(db)
    assert first["created"] == n and second["created"] == 0
    assert db.scalar(select(func.count()).select_from(m.Recommendation)) == n
    db.expire_all()
    rec = db.get(m.Recommendation, rec.id)
    assert rec.status == "In progress" and rec.notes == "Bearing replacement booked for Friday"


def test_rule_that_stops_triggering_is_marked_inactive_not_deleted(db):
    R.refresh(db)
    rec = db.scalar(select(m.Recommendation).where(m.Recommendation.rule_id == "downtime_high", m.Recommendation.entity_key == "M-B2"))
    rec.entity_key = "M-GHOST"  # simulate a stale record that no rule produces any more
    db.commit()
    out = R.refresh(db)
    db.expire_all()
    assert out["deactivated"] >= 1
    assert db.get(m.Recommendation, rec.id).active is False


def test_no_data_means_no_recommendations(tiny):
    sf = tiny()
    with sf() as db:
        assert R.evaluate_rules(db) == []


def test_status_change_persists_through_api(client):
    client.post("/api/recommendations/refresh")
    recs = client.get("/api/recommendations").json()
    assert recs and recs[0]["severity"] == "High"  # sorted by severity
    rid = recs[0]["id"]
    r = client.patch(f"/api/recommendations/{rid}", json={"status": "Resolved", "notes": "Fixed on 24 Oct"})
    assert r.status_code == 200 and r.json()["status"] == "Resolved"
    again = {x["id"]: x for x in client.get("/api/recommendations").json()}
    assert again[rid]["status"] == "Resolved" and again[rid]["notes"] == "Fixed on 24 Oct"
    assert client.get("/api/recommendations?status=Resolved").json()[0]["id"] == rid
    cards = {c["key"]: c for c in client.get("/api/dashboard/summary").json()["cards"]}
    open_high = sum(1 for x in again.values() if x["status"] == "Open" and x["severity"] == "High")
    assert cards["recs"]["value"] == open_high


def test_recommendation_api_validation(client):
    client.post("/api/recommendations/refresh")
    rid = client.get("/api/recommendations").json()[0]["id"]
    assert client.patch(f"/api/recommendations/{rid}", json={"status": "Done"}).status_code == 422
    assert client.patch(f"/api/recommendations/{rid}", json={}).status_code == 422
    assert client.patch("/api/recommendations/999999", json={"status": "Open"}).status_code == 404
    assert client.get("/api/recommendations?severity=Critical").status_code == 422
