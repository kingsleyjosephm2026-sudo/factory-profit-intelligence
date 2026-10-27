"""Health, configuration, reference data, record listings and exports."""
import io
from datetime import datetime, time, timedelta
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select

from .. import models as m
from ..config import get_settings
from ..deps import DB, F
from ..schemas import Page
from ..services import analytics as A
from ..services.metrics_docs import METRICS

router = APIRouter(prefix="/api")
PageQ = Annotated[int, Query(ge=1, le=100000)]
SizeQ = Annotated[int, Query(ge=1, le=500)]


@router.get("/health")
def health(db: DB):
    db.execute(select(1))
    return {"status": "ok", "time": datetime.utcnow().isoformat() + "Z", "database": "reachable"}


@router.get("/config")
def config(db: DB):
    cfg = get_settings()
    lo, hi = A.data_bounds(db)
    last_import = db.scalar(select(func.max(m.ImportLog.created_at)).where(m.ImportLog.status.in_(["success", "partial"])))
    sources = dict(db.execute(select(m.ProductionRecord.source, func.count()).group_by(m.ProductionRecord.source)).all())
    return dict(
        app="Factory Profit Intelligence", data_label="SIMULATED DEMO DATA" if (sources.get("import", 0) == 0) else "DEMO + IMPORTED DATA",
        currency=cfg.currency, data_from=lo.isoformat() if lo else None, data_to=hi.isoformat() if hi else None,
        production_records=sum(sources.values()), record_sources=sources, last_import_at=last_import.isoformat() + "Z" if last_import else None,
        database="sqlite" if cfg.database_url.startswith("sqlite") else "postgresql",
        assumptions=dict(downtime_unrecoverable_share=cfg.downtime_unrecoverable_share, scrap_salvage_rate=cfg.scrap_salvage_rate, energy_tolerance_pct=cfg.energy_tolerance_pct,
                         material_allowance_pct=cfg.material_allowance_pct, carrying_rate_annual=cfg.carrying_rate_annual, max_days_cover=cfg.max_days_cover,
                         benchmark_unplanned_downtime_pct=cfg.benchmark_unplanned_downtime_pct, benchmark_defect_rate_pct=cfg.benchmark_defect_rate_pct,
                         realization_factor=cfg.realization_factor, target_efficiency=cfg.target_efficiency),
        warning="Demo only: no authentication, not production-hardened. Data is simulated and not connected to real machinery.",
    )


@router.get("/metrics")
def metrics():
    return METRICS


@router.get("/factories")
def factories(db: DB):
    out = []
    for f in db.scalars(select(m.Factory)):
        out.append(dict(id=f.id, name=f.name, location=f.location, currency=f.currency,
                        lines=[dict(id=ln.id, code=ln.code, name=ln.name, machines=len(ln.machines)) for ln in f.lines]))
    return out


@router.get("/machines")
def machines(db: DB):
    rows = db.execute(select(m.Machine, m.ProductionLine.name, m.ProductionLine.code).join(m.ProductionLine)).all()
    return [dict(id=r.id, code=r.code, name=r.name, line_id=r.line_id, line_name=ln, line_code=lc, rated_units_per_hour=r.rated_units_per_hour, power_kw=r.power_kw, crew_size=r.crew_size)
            for r, ln, lc in rows]


@router.get("/products")
def products(db: DB):
    return [dict(id=p.id, sku=p.sku, name=p.name, category=p.category, unit_price=p.unit_price, std_material_cost=p.std_material_cost,
                 std_conversion_cost=p.std_conversion_cost, contribution_margin=p.contribution_margin, speed_factor=p.speed_factor) for p in db.scalars(select(m.Product))]


# ----------------------------------------------------------------------------- record listings
PROD_SORT = {"period_start": "period_start", "units": "units", "defective": "defective", "unpl_down": "unpl_down", "target": "target"}


@router.get("/production", response_model=Page)
def production(db: DB, f: F, page: PageQ = 1, page_size: SizeQ = 50, sort_by: Literal["period_start", "units", "defective", "unpl_down", "target"] = "period_start",
               desc: bool = True, machine_code: Annotated[str | None, Query(max_length=30)] = None):
    stmt = A.production_select().where(*A._clauses(f))
    if machine_code:
        stmt = stmt.where(m.Machine.code == machine_code)
    col = {"period_start": m.ProductionRecord.period_start, "units": m.ProductionRecord.units_produced, "defective": m.ProductionRecord.defective_units,
           "unpl_down": m.ProductionRecord.unplanned_downtime_min, "target": m.ProductionRecord.target_units}[sort_by]
    return A.paginate(stmt.order_by(col.desc() if desc else col.asc(), m.ProductionRecord.id), db, page, page_size)


@router.get("/downtime", response_model=Page)
def downtime(db: DB, f: F, page: PageQ = 1, page_size: SizeQ = 50, planned: bool | None = None):
    E, M = m.DowntimeEvent, m.Machine
    stmt = (select(E.id, E.start_ts, E.duration_min, E.planned, E.reason_code, E.source, M.code.label("machine_code"))
            .join(M, M.id == E.machine_id)
            .where(E.start_ts >= datetime.combine(f.date_from, time.min), E.start_ts < datetime.combine(f.date_to + timedelta(days=1), time.min)))
    if f.line_id is not None:
        stmt = stmt.where(M.line_id == f.line_id)
    if f.machine_id is not None:
        stmt = stmt.where(E.machine_id == f.machine_id)
    if planned is not None:
        stmt = stmt.where(E.planned == planned)
    return A.paginate(stmt.order_by(E.start_ts.desc(), E.id), db, page, page_size)


@router.get("/quality", response_model=Page)
def quality(db: DB, f: F, page: PageQ = 1, page_size: SizeQ = 50):
    Q, P, M = m.QualityRecord, m.ProductionRecord, m.Machine
    stmt = (select(Q.id, Q.production_record_id, Q.defect_category, Q.defective_units, P.period_start, P.shift, M.code.label("machine_code"))
            .join(P, P.id == Q.production_record_id).join(M, M.id == P.machine_id).where(*A._clauses(f)))
    return A.paginate(stmt.order_by(P.period_start.desc(), Q.id), db, page, page_size)


@router.get("/energy", response_model=Page)
def energy(db: DB, f: F, page: PageQ = 1, page_size: SizeQ = 50):
    E, P, M = m.EnergyRecord, m.ProductionRecord, m.Machine
    stmt = (select(E.id, E.period_start, E.kwh, E.tariff, (E.kwh * E.tariff).label("cost"), E.source, M.code.label("machine_code"))
            .join(M, M.id == E.machine_id).join(P, (P.machine_id == E.machine_id) & (P.period_start == E.period_start)).where(*A._clauses(f)))
    return A.paginate(stmt.order_by(E.period_start.desc(), E.id), db, page, page_size)


@router.get("/inventory", response_model=Page)
def inventory(db: DB, f: F, page: PageQ = 1, page_size: SizeQ = 50):
    S = m.InventorySnapshot
    stmt = select(S.id, S.item_code, S.item_name, S.snapshot_date, S.quantity_on_hand, S.reorder_point, S.unit_cost, S.avg_daily_usage, S.source).where(
        S.snapshot_date >= f.date_from, S.snapshot_date <= f.date_to)
    if f.line_id is not None:
        stmt = stmt.where(S.line_id == f.line_id)
    return A.paginate(stmt.order_by(S.snapshot_date.desc(), S.item_code), db, page, page_size)


@router.get("/maintenance", response_model=Page)
def maintenance(db: DB, page: PageQ = 1, page_size: SizeQ = 50):
    X, M = m.MaintenanceEvent, m.Machine
    stmt = select(X.id, X.event_ts, X.category, X.duration_min, X.cost, X.source, M.code.label("machine_code")).join(M, M.id == X.machine_id)
    return A.paginate(stmt.order_by(X.event_ts.desc(), X.id), db, page, page_size)


# ----------------------------------------------------------------------------- export
EXPORT_LIMIT = 200_000


def _safe_cell(v):
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v  # neutralise spreadsheet formula injection
    return v


@router.get("/export/{dataset}")
def export(dataset: Literal["production", "downtime", "quality", "energy", "inventory", "loss"], db: DB, f: F,
           format: Literal["csv", "xlsx"] = "csv", by: Literal["machine", "line", "product", "shift", "date"] = "machine"):
    cfg = get_settings()
    if dataset == "production":
        df = A.load_frame(db, f, cfg)
        cols = ["id", "period_start", "shift", "machine_code", "line_name", "product_sku", "units", "defective", "target", "planned_down", "unpl_down", "kwh", "tariff",
                "energy_cost", "material_cost", "labor_hours", "labor_cost", "loss_downtime", "loss_quality", "loss_energy", "loss_material", "source"]
        df = df[cols]
    elif dataset == "downtime":
        df = A.event_frame(db, f).drop(columns=["machine_id", "line_id"], errors="ignore")
    elif dataset == "quality":
        Q, P, M = m.QualityRecord, m.ProductionRecord, m.Machine
        df = pd.read_sql(select(Q.id, Q.production_record_id, Q.defect_category, Q.defective_units, P.period_start, P.shift, M.code.label("machine_code"))
                         .join(P, P.id == Q.production_record_id).join(M, M.id == P.machine_id).where(*A._clauses(f)), db.connection())
    elif dataset == "energy":
        df = A.load_frame(db, f, cfg)
        df = df[df.has_energy][["period_start", "machine_code", "shift", "kwh", "tariff", "energy_cost", "excess_kwh", "loss_energy"]]
    elif dataset == "inventory":
        df = A.inventory_costs(A.inventory_frame(db, f), cfg)
    else:
        df = pd.DataFrame(A.loss_breakdown(db, f, by, cfg=cfg))
    if len(df) > EXPORT_LIMIT:
        raise HTTPException(413, f"Export is limited to {EXPORT_LIMIT:,} rows; narrow the date range.")
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].map(_safe_cell)
    name = f"fpi_{dataset}_{f.date_from}_{f.date_to}"
    if format == "xlsx":
        buf = io.BytesIO()
        df.to_excel(buf, index=False, sheet_name=dataset[:30])
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return Response(df.to_csv(index=False), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
