"""CSV ingestion: validate, preview, de-duplicate and commit. A malformed file never crashes the app or partially
corrupts data: all inserts happen in one transaction and are rolled back on any unexpected error."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import Settings, get_settings
from .datagen import shift_of

MAX_ERRORS_RETURNED = 200
PREVIEW_ROWS = 10


class IngestionError(Exception):
    """File-level failure (bad header, encoding, size...). `status` is the HTTP status to return."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ----------------------------------------------------------------------------- field parsers
def _num(lo=None, hi=None, integer=False):
    def parse(raw: str):
        if raw is None or str(raw).strip() == "":
            raise ValueError("is missing")
        try:
            v = float(str(raw).replace(",", ""))
        except ValueError:
            raise ValueError(f"'{raw}' is not a number") from None
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("must be a finite number")
        if integer:
            if v != int(v):
                raise ValueError(f"'{raw}' must be a whole number")
            v = int(v)
        if lo is not None and v < lo:
            raise ValueError(f"{v} is below the minimum of {lo}")
        if hi is not None and v > hi:
            raise ValueError(f"{v} is above the maximum of {hi}")
        return v
    return parse


def _ts(raw: str) -> datetime:
    if raw is None or str(raw).strip() == "":
        raise ValueError("is missing")
    try:
        v = datetime.fromisoformat(str(raw).strip().replace("Z", ""))
    except ValueError:
        raise ValueError(f"'{raw}' is not a valid timestamp (use YYYY-MM-DD HH:MM[:SS])") from None
    if v.tzinfo is not None:
        raise ValueError("timestamps must be factory-local without a timezone offset")
    if not (2000 <= v.year <= 2100):
        raise ValueError(f"year {v.year} is outside 2000-2100")
    return v


def _date(raw: str) -> date:
    return _ts(raw).date()


def _text(raw: str, maxlen=120):
    s = (raw or "").strip()
    if not s:
        raise ValueError("is missing")
    if len(s) > maxlen:
        raise ValueError(f"is longer than {maxlen} characters")
    return s


def _bool(raw: str) -> bool:
    s = (raw or "").strip().lower()
    if s in ("1", "true", "yes", "y", "planned"):
        return True
    if s in ("0", "false", "no", "n", "unplanned"):
        return False
    raise ValueError(f"'{raw}' must be true/false")


@dataclass
class Spec:
    columns: dict[str, Callable]
    optional: dict[str, Callable] = field(default_factory=dict)
    key: tuple[str, ...] = ()
    example: list[dict] = field(default_factory=list)


SPECS: dict[str, Spec] = {
    "production": Spec(
        columns=dict(machine_code=_text, product_sku=_text, period_start=_ts, period_minutes=_num(1, 1440, True), planned_downtime_min=_num(0, 1440),
                     unplanned_downtime_min=_num(0, 1440), units_produced=_num(0, 10_000_000, True), defective_units=_num(0, 10_000_000, True),
                     target_units=_num(0, 10_000_000, True), material_cost=_num(0), labor_hours=_num(0, 10_000), labor_cost=_num(0)),
        optional=dict(shift=_text), key=("machine_code", "period_start"),
        example=[dict(machine_code="M-A1", product_sku="P-A01", period_start="2026-11-01 06:00", period_minutes=480, planned_downtime_min=0, unplanned_downtime_min=24,
                      units_produced=1650, defective_units=26, target_units=1600, material_cost=47100, labor_hours=16, labor_cost=3680, shift="A")],
    ),
    "downtime": Spec(
        columns=dict(machine_code=_text, start_ts=_ts, duration_min=_num(0.1, 1440), planned=_bool, reason_code=lambda r: _text(r, 40).upper()),
        key=("machine_code", "start_ts"),
        example=[dict(machine_code="M-A1", start_ts="2026-11-01 08:15:00", duration_min=18.5, planned="false", reason_code="JAM")],
    ),
    "energy": Spec(
        columns=dict(machine_code=_text, period_start=_ts, kwh=_num(0, 1_000_000), tariff=_num(0, 1000)), key=("machine_code", "period_start"),
        example=[dict(machine_code="M-A1", period_start="2026-11-01 06:00", kwh=290.5, tariff=6.8)],
    ),
    "inventory": Spec(
        columns=dict(line_code=_text, item_code=_text, item_name=_text, snapshot_date=_date, quantity_on_hand=_num(0), reorder_point=_num(0), unit_cost=_num(0), avg_daily_usage=_num(0)),
        key=("item_code", "snapshot_date"),
        example=[dict(line_code="LA", item_code="RM-PP", item_name="PP Granules (kg)", snapshot_date="2026-11-01", quantity_on_hand=5200, reorder_point=3700, unit_cost=95, avg_daily_usage=520)],
    ),
}


def template_csv(dataset: str) -> str:
    spec = SPECS[dataset]
    cols = list(spec.columns) + list(spec.optional)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for row in spec.example:
        w.writerow({c: row.get(c, "") for c in cols})
    return buf.getvalue()


# ----------------------------------------------------------------------------- validation
@dataclass
class Validation:
    dataset: str
    total: int = 0
    accepted: list[dict] = field(default_factory=list)  # parsed rows ready to insert
    errors: list[dict] = field(default_factory=list)
    duplicates: int = 0
    preview: list[dict] = field(default_factory=list)

    @property
    def rejected(self) -> int:
        return self.total - len(self.accepted)

    def summary(self) -> dict:
        return dict(dataset=self.dataset, rows_total=self.total, rows_valid=len(self.accepted), rows_rejected=self.rejected, rows_duplicate=self.duplicates,
                    errors=self.errors[:MAX_ERRORS_RETURNED], errors_truncated=len(self.errors) > MAX_ERRORS_RETURNED, preview=self.preview)


def read_upload(content: bytes, filename: str, cfg: Settings) -> str:
    if not filename.lower().endswith(".csv"):
        raise IngestionError("Only .csv files are accepted.", 415)
    if len(content) > cfg.max_upload_mb * 1024 * 1024:
        raise IngestionError(f"File exceeds the {cfg.max_upload_mb} MB limit.", 413)
    if not content.strip():
        raise IngestionError("The file is empty.")
    if b"\x00" in content[:4096]:
        raise IngestionError("The file looks binary, not CSV text.", 415)
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IngestionError("The file is not valid UTF-8 text. Re-save it as 'CSV UTF-8'.") from None


def parse_rows(text: str, spec: Spec, cfg: Settings) -> list[dict]:
    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.count("\n") else csv.excel
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise IngestionError("The file has no header row.")
    header = [h.strip() for h in reader.fieldnames]
    missing = [c for c in spec.columns if c not in header]
    if missing:
        raise IngestionError(f"Missing required column(s): {', '.join(missing)}. Expected: {', '.join(list(spec.columns) + list(spec.optional))}.")
    rows = []
    try:
        for i, raw in enumerate(reader, start=2):  # row 1 is the header
            if i - 1 > cfg.max_upload_rows:
                raise IngestionError(f"File has more than {cfg.max_upload_rows:,} rows; split it into smaller files.", 413)
            rows.append((i, {(k or "").strip(): (v if v is not None else "") for k, v in raw.items()}))
    except csv.Error as e:
        raise IngestionError(f"The CSV could not be parsed: {e}") from None
    if not rows:
        raise IngestionError("The file contains a header but no data rows.")
    return rows


def validate(db: Session, dataset: str, content: bytes, filename: str, cfg: Settings | None = None) -> Validation:
    cfg = cfg or get_settings()
    if dataset not in SPECS:
        raise IngestionError(f"Unknown dataset '{dataset}'. Choose one of: {', '.join(SPECS)}.", 404)
    spec = SPECS[dataset]
    text = read_upload(content, filename, cfg)
    rows = parse_rows(text, spec, cfg)
    machines = {mc.code: mc.id for mc in db.scalars(select(m.Machine))}
    products = {p.sku: p.id for p in db.scalars(select(m.Product))}
    lines = {ln.code: ln.id for ln in db.scalars(select(m.ProductionLine))}

    v = Validation(dataset=dataset, total=len(rows))
    parsed: list[tuple[int, dict]] = []
    for rownum, raw in rows:
        errs, out = [], {}
        for col, fn in {**spec.columns, **spec.optional}.items():
            val = raw.get(col, "")
            if col in spec.optional and str(val).strip() == "":
                continue
            try:
                out[col] = fn(val)
            except ValueError as e:
                errs.append(dict(row=rownum, column=col, message=f"{col} {e}"))
        if not errs:
            errs += _cross_checks(dataset, out, machines, products, lines, rownum)
        if errs:
            v.errors += errs
        else:
            parsed.append((rownum, out))

    # duplicates inside the file (first occurrence wins) and against existing data
    seen: set = set()
    existing = _existing_keys(db, dataset, [r for _n, r in parsed], machines)
    for rownum, row in parsed:
        key = tuple(row[k] for k in spec.key)
        if key in seen:
            v.errors.append(dict(row=rownum, column="/".join(spec.key), message="duplicate of an earlier row in this file"))
            v.duplicates += 1
        elif key in existing:
            v.errors.append(dict(row=rownum, column="/".join(spec.key), message="duplicate of a record already in the database"))
            v.duplicates += 1
        else:
            seen.add(key)
            v.accepted.append(row)
    v.errors.sort(key=lambda e: e["row"])
    v.preview = [{k: (x.isoformat(" ") if isinstance(x, datetime) else x.isoformat() if isinstance(x, date) else x) for k, x in r.items()} for r in v.accepted[:PREVIEW_ROWS]]
    return v


def _cross_checks(dataset, row, machines, products, lines, rownum) -> list[dict]:
    errs = []

    def e(col, msg):
        errs.append(dict(row=rownum, column=col, message=msg))

    if "machine_code" in row and row["machine_code"] not in machines:
        e("machine_code", f"unknown machine '{row['machine_code']}'")
    if dataset == "production":
        if row["product_sku"] not in products:
            e("product_sku", f"unknown product '{row['product_sku']}'")
        if row["defective_units"] > row["units_produced"]:
            e("defective_units", "defective_units cannot exceed units_produced")
        if row["planned_downtime_min"] + row["unplanned_downtime_min"] > row["period_minutes"] + 1e-6:
            e("unplanned_downtime_min", "planned + unplanned downtime exceeds period_minutes")
        if "shift" in row and row["shift"].upper() not in ("A", "B", "C"):
            e("shift", "shift must be A, B or C")
    if dataset == "inventory" and row["line_code"] not in lines:
        e("line_code", f"unknown line '{row['line_code']}'")
    return errs


def _existing_keys(db: Session, dataset: str, rows: list[dict], machines: dict) -> set:
    if not rows:
        return set()
    inv_machines = {v: k for k, v in machines.items()}
    if dataset == "production":
        lo, hi = min(r["period_start"] for r in rows), max(r["period_start"] for r in rows)
        q = select(m.ProductionRecord.machine_id, m.ProductionRecord.period_start).where(m.ProductionRecord.period_start.between(lo, hi))
        return {(inv_machines[a], b if isinstance(b, datetime) else datetime.fromisoformat(str(b))) for a, b in db.execute(q)}
    if dataset == "energy":
        lo, hi = min(r["period_start"] for r in rows), max(r["period_start"] for r in rows)
        q = select(m.EnergyRecord.machine_id, m.EnergyRecord.period_start).where(m.EnergyRecord.period_start.between(lo, hi))
        return {(inv_machines[a], b if isinstance(b, datetime) else datetime.fromisoformat(str(b))) for a, b in db.execute(q)}
    if dataset == "downtime":
        lo, hi = min(r["start_ts"] for r in rows), max(r["start_ts"] for r in rows)
        q = select(m.DowntimeEvent.machine_id, m.DowntimeEvent.start_ts).where(m.DowntimeEvent.start_ts.between(lo, hi))
        return {(inv_machines[a], b if isinstance(b, datetime) else datetime.fromisoformat(str(b))) for a, b in db.execute(q)}
    lo, hi = min(r["snapshot_date"] for r in rows), max(r["snapshot_date"] for r in rows)
    q = select(m.InventorySnapshot.item_code, m.InventorySnapshot.snapshot_date).where(m.InventorySnapshot.snapshot_date.between(lo, hi))
    return {(a, b if isinstance(b, date) and not isinstance(b, datetime) else date.fromisoformat(str(b)[:10])) for a, b in db.execute(q)}


# ----------------------------------------------------------------------------- commit
def commit(db: Session, dataset: str, content: bytes, filename: str, mode: str = "skip_invalid", force: bool = False, cfg: Settings | None = None) -> dict:
    cfg = cfg or get_settings()
    if mode not in ("skip_invalid", "all_or_nothing"):
        raise IngestionError("mode must be 'skip_invalid' or 'all_or_nothing'.")
    sha = hashlib.sha256(content).hexdigest()
    prior = db.scalar(select(m.ImportLog).where(m.ImportLog.dataset == dataset, m.ImportLog.file_sha256 == sha, m.ImportLog.status.in_(["success", "partial"])).limit(1))
    if prior is not None and not force:
        raise IngestionError(f"This exact file was already imported on {prior.created_at:%Y-%m-%d %H:%M} (import #{prior.id}). Pass force=true to import it again.", 409)

    try:
        v = validate(db, dataset, content, filename, cfg)
    except IngestionError as e:
        if e.status not in (404, 413, 415):  # still log parse failures; skip oversize/unsupported types
            _log(db, dataset, filename, sha, "failed", mode, 0, 0, 0, 0, str(e), [])
        raise
    if mode == "all_or_nothing" and v.rejected:
        log = _log(db, dataset, filename, sha, "failed", mode, v.total, 0, v.rejected, v.duplicates, "all_or_nothing: file rejected because of invalid rows; nothing was imported.", v.errors)
        return dict(import_id=log.id, status="failed", **v.summary(), rows_imported=0, message="Nothing imported: the file contains invalid rows and mode is all_or_nothing.")
    if not v.accepted:
        log = _log(db, dataset, filename, sha, "failed", mode, v.total, 0, v.rejected, v.duplicates, "No valid rows to import.", v.errors)
        return dict(import_id=log.id, status="failed", **v.summary(), rows_imported=0, message="No valid rows to import.")

    log = _log(db, dataset, filename, sha, "success", mode, v.total, len(v.accepted), v.rejected, v.duplicates, "", v.errors, commit_now=False)
    try:
        _insert(db, dataset, v.accepted, log.id)
        log.status = "success" if not v.rejected else "partial"
        log.message = f"Imported {len(v.accepted)} of {v.total} rows."
        db.commit()
    except Exception as e:  # noqa: BLE001 - roll back everything, record the failure, never leave partial data
        db.rollback()
        log2 = _log(db, dataset, filename, sha, "failed", mode, v.total, 0, v.total, 0, f"Database error, nothing imported: {type(e).__name__}", [])
        raise IngestionError("The database rejected the data; nothing was imported. Check for constraint violations.", 422) from e
    return dict(import_id=log.id, status=log.status, **v.summary(), rows_imported=len(v.accepted), message=log.message)


def _log(db, dataset, filename, sha, status, mode, total, ok, rej, dup, msg, errors, commit_now=True) -> m.ImportLog:
    log = m.ImportLog(dataset=dataset, filename=filename[:255], file_sha256=sha, status=status, mode=mode, rows_total=total, rows_accepted=ok,
                      rows_rejected=rej, rows_duplicate=dup, message=msg, errors_json=json.dumps(errors[:MAX_ERRORS_RETURNED]))
    db.add(log)
    if commit_now:
        db.commit()
    else:
        db.flush()
    return log


def _insert(db: Session, dataset: str, rows: list[dict], import_id: int) -> None:
    machines = {mc.code: mc.id for mc in db.scalars(select(m.Machine))}
    products = {p.sku: p.id for p in db.scalars(select(m.Product))}
    lines = {ln.code: ln.id for ln in db.scalars(select(m.ProductionLine))}
    for r in rows:
        if dataset == "production":
            rec = m.ProductionRecord(
                machine_id=machines[r["machine_code"]], product_id=products[r["product_sku"]], period_start=r["period_start"], period_minutes=r["period_minutes"],
                shift=r.get("shift", "").upper() or shift_of(r["period_start"]), planned_downtime_min=r["planned_downtime_min"], unplanned_downtime_min=r["unplanned_downtime_min"],
                units_produced=r["units_produced"], defective_units=r["defective_units"], target_units=r["target_units"], material_cost=r["material_cost"],
                labor_hours=r["labor_hours"], labor_cost=r["labor_cost"], source="import", import_id=import_id)
            if r["defective_units"] > 0:  # no category supplied; keep quality totals reconcilable
                rec.quality = [m.QualityRecord(defect_category="Unclassified", defective_units=r["defective_units"])]
            db.add(rec)
        elif dataset == "downtime":
            db.add(m.DowntimeEvent(machine_id=machines[r["machine_code"]], start_ts=r["start_ts"], duration_min=r["duration_min"], planned=r["planned"],
                                   reason_code=r["reason_code"], source="import", import_id=import_id))
        elif dataset == "energy":
            db.add(m.EnergyRecord(machine_id=machines[r["machine_code"]], period_start=r["period_start"], kwh=r["kwh"], tariff=r["tariff"], source="import", import_id=import_id))
        else:
            db.add(m.InventorySnapshot(line_id=lines[r["line_code"]], item_code=r["item_code"], item_name=r["item_name"], snapshot_date=r["snapshot_date"],
                                       quantity_on_hand=r["quantity_on_hand"], reorder_point=r["reorder_point"], unit_cost=r["unit_cost"],
                                       avg_daily_usage=r["avg_daily_usage"], source="import", import_id=import_id))
    db.flush()
