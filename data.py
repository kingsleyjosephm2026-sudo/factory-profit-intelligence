"""CSV import, demo data generation and live-simulation controls."""
import json
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, select

from .. import models as m
from ..config import get_settings
from ..deps import DB
from ..services import analytics as A
from ..services import datagen, ingestion, recommendations

router = APIRouter(prefix="/api")
Dataset = Literal["production", "downtime", "energy", "inventory"]


async def _read(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)  # never buffer more than the limit
    return data


def _raise(e: ingestion.IngestionError):
    raise HTTPException(e.status, str(e))


@router.get("/imports/templates/{dataset}")
def template(dataset: Dataset):
    return Response(ingestion.template_csv(dataset), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="fpi_{dataset}_template.csv"'})


@router.post("/imports/validate")
async def validate_upload(dataset: Annotated[Dataset, Form()], file: Annotated[UploadFile, File()], db: DB):
    """Dry run: validate and preview without writing anything."""
    cfg = get_settings()
    try:
        content = await _read(file, cfg.max_upload_mb * 1024 * 1024)
        return ingestion.validate(db, dataset, content, file.filename or "upload.csv", cfg).summary()
    except ingestion.IngestionError as e:
        _raise(e)


@router.post("/imports")
async def import_upload(dataset: Annotated[Dataset, Form()], file: Annotated[UploadFile, File()], db: DB,
                        mode: Annotated[Literal["skip_invalid", "all_or_nothing"], Form()] = "skip_invalid", force: Annotated[bool, Form()] = False):
    cfg = get_settings()
    try:
        content = await _read(file, cfg.max_upload_mb * 1024 * 1024)
        return ingestion.commit(db, dataset, content, file.filename or "upload.csv", mode, force, cfg)
    except ingestion.IngestionError as e:
        _raise(e)


@router.get("/imports")
def import_history(db: DB):
    rows = db.scalars(select(m.ImportLog).order_by(m.ImportLog.id.desc()).limit(100))
    return [dict(id=r.id, dataset=r.dataset, filename=r.filename, status=r.status, mode=r.mode, rows_total=r.rows_total, rows_accepted=r.rows_accepted,
                 rows_rejected=r.rows_rejected, rows_duplicate=r.rows_duplicate, message=r.message, created_at=r.created_at.isoformat() + "Z",
                 errors=json.loads(r.errors_json or "[]")[:20]) for r in rows]


@router.post("/demo/generate")
def generate_demo(db: DB, force: bool = False):
    """Generate the reproducible SIMULATED dataset. Refuses to touch existing data unless force=true."""
    cfg = get_settings()
    n = db.scalar(select(func.count()).select_from(m.ProductionRecord)) or 0
    if n and not force:
        raise HTTPException(409, "Data already exists. Pass force=true to wipe transactional data and regenerate the demo dataset.")
    if n:
        datagen.wipe_all_data(db)
    out = datagen.generate_history(db, cfg.demo_days, None, cfg.seed)
    out["recommendations"] = recommendations.refresh(db)
    return out


@router.get("/simulation")
def sim_status(request: Request, db: DB):
    return request.app.state.simulator.status(db)


@router.get("/live/status")
def live_status(request: Request, db: DB):
    """Current operational status for the live monitor: simulation state plus the latest interval per machine."""
    sim = request.app.state.simulator
    status = sim.status(db)
    P, M = m.ProductionRecord, m.Machine
    latest = db.execute(select(P.machine_id, func.max(P.period_start)).group_by(P.machine_id)).all()
    machines = []
    for mid, ts in latest:
        r = db.execute(select(P, M.code, M.name).join(M, M.id == P.machine_id).where(P.machine_id == mid, P.period_start == ts)).first()
        if r is None:
            continue
        rec, code, name = r
        machines.append(dict(machine_code=code, machine_name=name, period_start=rec.period_start.isoformat(), units=rec.units_produced, defective=rec.defective_units,
                             unplanned_downtime_min=rec.unplanned_downtime_min, state="down" if rec.unplanned_downtime_min > 0 and rec.units_produced == 0 else
                             "stopped_part" if rec.unplanned_downtime_min > 0 else "running", source=rec.source))
    machines.sort(key=lambda x: x["machine_code"])
    E, X = m.DowntimeEvent, m.Machine
    ev = db.execute(select(E.start_ts, E.duration_min, E.reason_code, E.planned, X.code).join(X, X.id == E.machine_id).where(E.planned == False)  # noqa: E712
                    .order_by(E.start_ts.desc()).limit(8)).all()
    status["machines"] = machines
    status["recent_events"] = [dict(start_ts=a.isoformat(), duration_min=b, reason_code=c, machine_code=e) for a, b, c, _d, e in ev]
    return status


@router.post("/simulation/start")
def sim_start(request: Request, db: DB):
    if not db.scalar(select(m.ProductionRecord.id).limit(1)):
        raise HTTPException(409, "No data loaded. Generate the demo dataset first.")
    request.app.state.simulator.start()
    return request.app.state.simulator.status(db)


@router.post("/simulation/pause")
def sim_pause(request: Request, db: DB):
    request.app.state.simulator.pause()
    return request.app.state.simulator.status(db)


@router.post("/simulation/tick")
def sim_tick(request: Request, db: DB):
    """Advance the simulation by exactly one tick (useful for demos and tests)."""
    sim = request.app.state.simulator
    try:
        sim.tick()
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return sim.status(db)


@router.post("/simulation/reset")
def sim_reset(request: Request, db: DB):
    sim = request.app.state.simulator
    res = sim.reset()
    return {**sim.status(db), **res}
