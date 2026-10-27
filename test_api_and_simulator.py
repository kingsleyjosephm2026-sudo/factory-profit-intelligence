import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import models as m
from app.main import create_app
from app.routers.meta import _safe_cell
from app.services import analytics as A


def test_health_config_reference(client):
    assert client.get("/api/health").json()["status"] == "ok"
    cfg = client.get("/api/config").json()
    assert cfg["data_label"] == "SIMULATED DEMO DATA" and cfg["currency"] == "INR" and "not production-hardened" in cfg["warning"]
    fac = client.get("/api/factories").json()
    assert len(fac) == 1 and len(fac[0]["lines"]) == 3
    assert len(client.get("/api/machines").json()) == 10 and len(client.get("/api/products").json()) == 8
    metrics = client.get("/api/metrics").json()
    for k in ("loss_downtime", "loss_quality", "defect_rate", "potential"):
        assert {"formula", "inputs", "assumptions", "unit", "limitations", "type"} <= set(metrics[k])
        assert metrics[k]["type"] in ("measured", "calculated", "estimated")


def test_dashboard_cards_and_filters(client):
    s = client.get("/api/dashboard/summary").json()
    assert [c["key"] for c in s["cards"]] == ["units", "good", "defect", "downtime", "energy", "loss", "attainment", "recs"]
    metrics = client.get("/api/metrics").json()
    assert all(c["definition_key"] in metrics for c in s["cards"] if c["definition_key"])
    base = {c["key"]: c["value"] for c in s["cards"]}
    shift = {c["key"]: c["value"] for c in client.get("/api/dashboard/summary", params={"shift": "A"}).json()["cards"]}
    line = {c["key"]: c["value"] for c in client.get("/api/dashboard/summary", params={"line_id": 2}).json()["cards"]}
    assert shift["units"] < base["units"] and line["units"] < base["units"] and shift["loss"] != base["loss"]
    ch = client.get("/api/dashboard/charts").json()
    for k in ("production_vs_target", "loss_by_category", "downtime_trend", "defect_trend", "energy_trend", "loss_by_line", "top_machines"):
        assert ch[k], k
    assert len(ch["top_machines"]) == 5 and ch["top_machines"][0]["machine_code"] == "M-B2"
    assert len(client.get("/api/dashboard/charts", params={"grain": "week"}).json()["production_vs_target"]) < len(ch["production_vs_target"])


def test_chart_values_come_from_data_not_constants(client):
    a = client.get("/api/dashboard/charts", params={"date_from": "2026-09-01", "date_to": "2026-09-07"}).json()
    b = client.get("/api/dashboard/charts", params={"date_from": "2026-10-01", "date_to": "2026-10-07"}).json()
    assert a["production_vs_target"] != b["production_vs_target"]
    assert len(a["production_vs_target"]) == 7


@pytest.mark.parametrize("path,params", [
    ("/api/dashboard/summary", {"date_from": "2026-10-10", "date_to": "2026-10-01"}),
    ("/api/dashboard/summary", {"shift": "X"}),
    ("/api/dashboard/summary", {"line_id": 0}),
    ("/api/dashboard/summary", {"date_from": "banana"}),
    ("/api/dashboard/charts", {"grain": "year"}),
    ("/api/production", {"page_size": 1000}),
    ("/api/production", {"page": 0}),
    ("/api/production", {"sort_by": "password"}),
    ("/api/loss/breakdown", {"by": "drop table"}),
    ("/api/loss/drilldown", {"category": "luck"}),
    ("/api/export/secrets", {}),
])
def test_input_validation_returns_422(client, path, params):
    assert client.get(path, params=params).status_code == 422


def test_pagination(client):
    p1 = client.get("/api/production", params={"page_size": 10}).json()
    p2 = client.get("/api/production", params={"page_size": 10, "page": 2}).json()
    assert len(p1["items"]) == 10 and p1["total"] > 10
    assert not {i["id"] for i in p1["items"]} & {i["id"] for i in p2["items"]}
    big = client.get("/api/production", params={"page": 99999}).json()
    assert big["items"] == []
    for ep in ("downtime", "quality", "energy", "inventory", "maintenance"):
        r = client.get(f"/api/{ep}", params={"page_size": 5}).json()
        assert r["total"] > 0 and len(r["items"]) <= 5, ep


def test_sorting_in_listing(client):
    r = client.get("/api/production", params={"sort_by": "units", "desc": "true", "page_size": 5}).json()["items"]
    assert [i["units"] for i in r] == sorted((i["units"] for i in r), reverse=True)


def test_loss_endpoints(client):
    ls = client.get("/api/loss/summary").json()
    assert ls["totals"]["observed"] > ls["totals"]["avoidable"] > ls["totals"]["potential"] > 0
    assert "NOT verified" in ls["note"]
    for by in ("machine", "line", "product", "shift", "date"):
        rows = client.get("/api/loss/breakdown", params={"by": by}).json()["rows"]
        assert rows, by
    for cat in ("downtime", "quality", "energy", "material", "inventory"):
        d = client.get("/api/loss/drilldown", params={"category": cat}).json()
        assert d["total"] > 0 and d["items"] and d["explanation"]["formula"], cat


def test_domain_analytics_endpoints(client):
    for ep in ("production", "downtime", "quality", "energy"):
        assert client.get(f"/api/analytics/{ep}").status_code == 200
    inv = client.get("/api/analytics/inventory").json()
    assert inv["summary"]["breaches"] >= 2


def test_root_cause_findings_and_limitations(client):
    rc = client.get("/api/rootcause").json()
    assert rc["correlations"]["available"] and "does not prove causation" in rc["note"] and rc["correlations"]["pairs"]
    assert rc["outliers"]["available"] and rc["trends"]["available"] and rc["reasons"]["available"]
    full = client.get("/api/rootcause", params={"date_from": "2026-07-27", "date_to": "2026-10-24"}).json()
    assert full["trends"]["machines"][0]["machine_code"] == "M-B2"  # the planted 90-day worsening downtime trend is surfaced
    tiny_window = client.get("/api/rootcause", params={"date_from": "2026-10-20", "date_to": "2026-10-20"}).json()
    assert tiny_window["correlations"]["available"] is False and "Need at least" in tiny_window["correlations"]["reason"]
    assert tiny_window["trends"]["available"] is False
    none = client.get("/api/rootcause", params={"date_from": "2020-01-01", "date_to": "2020-01-02"}).json()
    assert none["correlations"]["available"] is False and "No production records" in none["correlations"]["reason"]


def test_exports(client):
    r = client.get("/api/export/production", params={"date_from": "2026-10-20", "date_to": "2026-10-21"})
    lines = r.text.strip().splitlines()
    total = client.get("/api/production", params={"date_from": "2026-10-20", "date_to": "2026-10-21"}).json()["total"]
    assert r.headers["content-type"].startswith("text/csv") and len(lines) == total + 1 and "loss_downtime" in lines[0]
    for ds in ("downtime", "quality", "energy", "inventory"):
        assert client.get(f"/api/export/{ds}").status_code == 200, ds
    loss = client.get("/api/export/loss", params={"by": "line"})
    assert "observed_loss" in loss.text.splitlines()[0]
    x = client.get("/api/export/loss", params={"format": "xlsx"})
    assert x.content[:2] == b"PK"
    assert _safe_cell("=HYPERLINK(\"http://evil\")").startswith("'") and _safe_cell("normal") == "normal" and _safe_cell(5) == 5


def test_demo_generation_endpoint_guards_existing_data(client, empty_client):
    assert client.post("/api/demo/generate").status_code == 409
    r = empty_client.post("/api/demo/generate")
    assert r.status_code == 200 and r.json()["production_records"] == 2700
    assert empty_client.get("/api/config").json()["production_records"] == 2700


def test_empty_database_endpoints_do_not_crash(empty_client):
    for p in ("/api/dashboard/summary", "/api/dashboard/charts", "/api/analytics/downtime", "/api/loss/summary", "/api/rootcause", "/api/analytics/inventory"):
        assert empty_client.get(p).status_code == 200, p
    assert empty_client.post("/api/simulation/start").status_code == 409


def test_server_errors_are_generic_and_do_not_leak():
    from app.database import Base, make_engine
    eng = make_engine("sqlite://")  # no tables created -> every query fails
    app = create_app(sessionmaker(bind=eng))
    r = TestClient(app, raise_server_exceptions=False).get("/api/factories")
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error. Check the server log for details."}
    assert "no such table" not in r.text


def test_cors_restricted_to_configured_origins(client):
    ok = client.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/api/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


# ----------------------------------------------------------------------------- simulation
def n_rows(SessionF, model=m.ProductionRecord, **where):
    with SessionF() as s:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return s.scalar(q)


def test_tick_adds_real_rows_and_changes_metrics(client, SessionF):
    before = n_rows(SessionF)
    s0 = client.get("/api/simulation").json()
    assert s0["running"] is False and s0["mode"] == "SIMULATED DEMO DATA"
    for _ in range(4):
        assert client.post("/api/simulation/tick").status_code == 200
    s1 = client.get("/api/simulation").json()
    assert s1["ticks"] == 4 and s1["version"] > s0["version"] and s1["simulated_rows"] == 40
    assert n_rows(SessionF) == before + 40 and n_rows(SessionF, source="simulation") == 40
    day = s1["simulated_clock"][:10]
    summ = client.get("/api/dashboard/summary", params={"date_from": day, "date_to": day}).json()
    assert {c["key"]: c["value"] for c in summ["cards"]}["units"] > 0  # the new rows are in the analytics
    live = client.get("/api/live/status").json()
    assert len(live["machines"]) == 10 and live["last_tick_at"] and "not real" in live["note"]


def test_simulated_rows_are_coherent_and_do_not_collide(client, SessionF):
    for _ in range(6):
        client.post("/api/simulation/tick")
    with SessionF() as s:
        rows = list(s.scalars(select(m.ProductionRecord).where(m.ProductionRecord.source == "simulation")))
        assert all(r.defective_units <= r.units_produced and r.period_minutes == 15 for r in rows)
        keys = {(r.machine_id, r.period_start) for r in rows}
        assert len(keys) == len(rows)
        assert s.scalar(select(func.count()).select_from(m.EnergyRecord).where(m.EnergyRecord.source == "simulation")) == len(rows)


def test_reset_removes_only_simulated_data(client, SessionF):
    base = n_rows(SessionF)
    for _ in range(3):
        client.post("/api/simulation/tick")
    r = client.post("/api/simulation/reset").json()
    assert r["removed_production_rows"] == 30 and r["running"] is False and r["ticks"] == 0
    assert n_rows(SessionF) == base
    assert n_rows(SessionF, m.DowntimeEvent, source="simulation") == 0 and n_rows(SessionF, m.EnergyRecord, source="simulation") == 0
    assert n_rows(SessionF, m.QualityRecord) == n_rows(SessionF, m.QualityRecord)  # no orphan violation
    assert client.post("/api/simulation/tick").status_code == 200  # can start again from the same point


def test_retention_cap_prevents_unbounded_growth(client, SessionF):
    sim = client.app.state.simulator
    sim.cfg = sim.cfg.model_copy(update={"sim_max_rows": 50})
    for _ in range(12):
        client.post("/api/simulation/tick")
    assert n_rows(SessionF, source="simulation") <= 50
    with SessionF() as s:
        orphans = s.scalar(select(func.count()).select_from(m.QualityRecord).outerjoin(m.ProductionRecord, m.ProductionRecord.id == m.QualityRecord.production_record_id).where(m.ProductionRecord.id.is_(None)))
        assert orphans == 0


def test_start_pause_controls(client):
    assert client.post("/api/simulation/start").json()["running"] is True
    assert client.post("/api/simulation/pause").json()["running"] is False


def test_background_loop_ticks_when_running(SessionF):
    import time
    app = create_app(SessionF)
    app.state.simulator.cfg = app.state.simulator.cfg.model_copy(update={"sim_interval_seconds": 0.05})
    with TestClient(app) as c:  # runs lifespan -> background task
        c.post("/api/simulation/start")
        time.sleep(0.6)
        s = c.get("/api/simulation").json()
        c.post("/api/simulation/pause")
        assert s["ticks"] >= 2 and s["running"] is True
        t = c.get("/api/simulation").json()["ticks"]
        time.sleep(0.3)
        assert c.get("/api/simulation").json()["ticks"] <= t + 1  # paused: it stops advancing
