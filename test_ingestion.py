import io

import pytest
from sqlalchemy import func, select

from app import models as m
from app.config import get_settings
from app.services import ingestion

HDR = "machine_code,product_sku,period_start,period_minutes,planned_downtime_min,unplanned_downtime_min,units_produced,defective_units,target_units,material_cost,labor_hours,labor_cost,shift\n"
GOOD = "M-A1,P-A01,2026-11-01 06:00,480,0,20,1600,25,1650,47000,16,3680,A\n"


def up(client, name, content, dataset="production", path="/api/imports", **form):
    return client.post(path, data={"dataset": dataset, **form}, files={"file": (name, content if isinstance(content, bytes) else content.encode(), "text/csv")})


def count(client_db, model=m.ProductionRecord):
    with client_db() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_valid_import_inserts_logs_and_reports(client, SessionF):
    before = count(SessionF)
    r = up(client, "ok.csv", HDR + GOOD + GOOD.replace("06:00", "14:00").replace(",A\n", ",B\n"))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success" and body["rows_imported"] == 2 and body["rows_rejected"] == 0
    assert count(SessionF) == before + 2
    hist = client.get("/api/imports").json()
    assert hist[0]["rows_accepted"] == 2 and hist[0]["dataset"] == "production"
    cfg = client.get("/api/config").json()
    assert cfg["last_import_at"] and cfg["data_label"] == "DEMO + IMPORTED DATA"
    with SessionF() as s:  # defects get a category so quality totals reconcile
        assert s.scalar(select(func.count()).select_from(m.QualityRecord).where(m.QualityRecord.defect_category == "Unclassified")) == 2


def test_bad_rows_are_rejected_with_clear_messages(client, SessionF):
    bad = HDR + GOOD + "\n".join([
        "M-A1,P-A01,not-a-date,480,0,20,1600,25,1650,47000,16,3680,A",
        "M-ZZ,P-A01,2026-11-02 06:00,480,0,20,1600,25,1650,47000,16,3680,A",
        "M-A2,P-A01,2026-11-02 06:00,480,0,20,-5,25,1650,47000,16,3680,A",
        "M-A2,P-A01,2026-11-03 06:00,480,0,20,100,500,1650,47000,16,3680,A",
        "M-A2,P-A01,2026-11-04 06:00,480,0,20,,5,1650,47000,16,3680,A",
        "M-A2,P-A01,2026-11-05 06:00,480,500,20,100,5,1650,47000,16,3680,A",
        "M-A1,P-A01,2026-11-01 06:00,480,0,20,1600,25,1650,47000,16,3680,A",
    ]) + "\n"
    before = count(SessionF)
    body = up(client, "bad.csv", bad).json()
    assert body["rows_valid"] == 1 and body["rows_rejected"] == 7 and body["rows_duplicate"] == 1 and body["status"] == "partial"
    assert count(SessionF) == before + 1
    msgs = {e["row"]: e["message"] for e in body["errors"]}
    assert "not a valid timestamp" in msgs[3] and "unknown machine" in msgs[4] and "below the minimum" in msgs[5]
    assert "cannot exceed" in msgs[6] and "is missing" in msgs[7] and "exceeds period" in msgs[8] and "duplicate" in msgs[9]


def test_existing_records_are_detected_as_duplicates(client):
    with_dup = HDR + "M-A1,P-A01,2026-10-20 06:00,480,0,20,1600,25,1650,47000,16,3680,A\n"
    body = up(client, "dup.csv", with_dup).json()
    assert body["rows_duplicate"] == 1 and body["status"] == "failed" and body["rows_imported"] == 0


def test_same_file_twice_requires_force(client):
    f = HDR + GOOD
    assert up(client, "a.csv", f).status_code == 200
    r = up(client, "a.csv", f)
    assert r.status_code == 409 and "already imported" in r.json()["detail"]
    assert up(client, "a.csv", f, force="true").status_code == 200  # allowed, but rows are then duplicates


def test_all_or_nothing_imports_nothing_when_any_row_is_bad(client, SessionF):
    before = count(SessionF)
    body = up(client, "m.csv", HDR + GOOD + "M-ZZ,P-A01,2026-11-02 06:00,480,0,20,1600,25,1650,47000,16,3680,A\n", mode="all_or_nothing").json()
    assert body["status"] == "failed" and body["rows_imported"] == 0 and count(SessionF) == before


def test_dry_run_writes_nothing(client, SessionF):
    before, logs = count(SessionF), count(SessionF, m.ImportLog)
    r = up(client, "v.csv", HDR + GOOD, path="/api/imports/validate").json()
    assert r["rows_valid"] == 1 and r["preview"][0]["machine_code"] == "M-A1"
    assert count(SessionF) == before and count(SessionF, m.ImportLog) == logs


@pytest.mark.parametrize("content,name,status,needle", [
    ("machine_code,units\nM-A1,5\n", "x.csv", 422, "Missing required column"),
    ("", "x.csv", 422, "empty"),
    (HDR, "x.csv", 422, "no data rows"),
    (b"\xff\xfe\x00bad", "x.csv", 415, "binary"),
    (b"machine_code\n\xe9\xe9\n", "x.csv", 422, "UTF-8"),
    ("a,b\n1,2\n", "x.xlsx", 415, "Only .csv"),
])
def test_malformed_files_fail_cleanly(client, content, name, status, needle):
    r = up(client, name, content)
    assert r.status_code == status and needle in r.json()["detail"]


def test_oversize_file_rejected(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    r = up(client, "big.csv", HDR + GOOD)
    assert r.status_code == 413


def test_database_failure_rolls_back_everything(client, SessionF, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full")
    original = ingestion._insert

    def half_insert(db, dataset, rows, import_id):
        original(db, dataset, rows[:1], import_id)  # write something, then fail
        boom()
    monkeypatch.setattr(ingestion, "_insert", half_insert)
    before = count(SessionF)
    r = up(client, "f.csv", HDR + GOOD + GOOD.replace("06:00", "14:00"))
    assert r.status_code == 422 and count(SessionF) == before
    assert "disk full" not in r.text  # internals are not leaked


@pytest.mark.parametrize("dataset,row,model", [
    ("downtime", "M-A1,2026-11-01 08:15:00,18.5,false,jam\n", m.DowntimeEvent),
    ("energy", "M-A1,2026-11-01 06:00,290.5,6.8\n", m.EnergyRecord),
    ("inventory", "LA,RM-PP,PP Granules,2026-11-01,5200,3700,95,520\n", m.InventorySnapshot),
])
def test_other_datasets_import(client, SessionF, dataset, row, model):
    header = ",".join(ingestion.SPECS[dataset].columns) + "\n"
    before = count(SessionF, model)
    assert up(client, "d.csv", header + row, dataset=dataset).json()["rows_imported"] == 1
    assert count(SessionF, model) == before + 1


def test_templates_are_valid_and_importable(client):
    for ds in ingestion.SPECS:
        t = client.get(f"/api/imports/templates/{ds}")
        assert t.status_code == 200 and t.text.startswith(next(iter(ingestion.SPECS[ds].columns)))
        v = up(client, "t.csv", t.text, dataset=ds, path="/api/imports/validate").json()
        assert v["rows_valid"] == 1 and v["rows_rejected"] == 0, (ds, v["errors"])


def test_unknown_dataset_rejected(client):
    assert up(client, "x.csv", HDR + GOOD, dataset="payroll").status_code == 422
    assert client.get("/api/imports/templates/payroll").status_code == 422


def test_imported_data_flows_into_analytics(client):
    up(client, "ok.csv", HDR + GOOD)
    r = client.get("/api/production", params={"date_from": "2026-11-01", "date_to": "2026-11-01"}).json()
    assert r["total"] == 1 and r["items"][0]["units"] == 1600
