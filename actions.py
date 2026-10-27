"""Recommendations and savings initiatives (persisted user actions)."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from .. import models as m
from ..deps import DB
from ..schemas import RecommendationOut, RecommendationPatch, SavingsCreate, SavingsOut, SavingsPatch
from ..services import recommendations as R
from ..services import savings as S
import json

router = APIRouter(prefix="/api")
SEV = {"High": 0, "Medium": 1, "Low": 2}


@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(db: DB, status: Literal["Open", "In progress", "Resolved", "Dismissed"] | None = None,
                         severity: Literal["High", "Medium", "Low"] | None = None, rule_id: Annotated[str | None, Query(max_length=40)] = None):
    q = select(m.Recommendation)
    if status:
        q = q.where(m.Recommendation.status == status)
    if severity:
        q = q.where(m.Recommendation.severity == severity)
    if rule_id:
        q = q.where(m.Recommendation.rule_id == rule_id)
    rows = list(db.scalars(q))
    rows.sort(key=lambda r: (SEV.get(r.severity, 3), -(r.estimated_opportunity or 0)))
    return rows


@router.post("/recommendations/refresh")
def refresh_recommendations(db: DB):
    return R.refresh(db)


@router.patch("/recommendations/{rec_id}", response_model=RecommendationOut)
def patch_recommendation(rec_id: int, body: RecommendationPatch, db: DB):
    rec = db.get(m.Recommendation, rec_id)
    if rec is None:
        raise HTTPException(404, "Recommendation not found")
    if body.status is not None:
        rec.status = body.status
    if body.notes is not None:
        rec.notes = body.notes
    rec.updated_at = datetime.utcnow()
    db.commit()
    return rec


# ----------------------------------------------------------------------------- savings
def _scope_exists(db, scope_type, scope_id):
    if scope_type == "line" and db.get(m.ProductionLine, scope_id) is None:
        raise HTTPException(422, f"Production line {scope_id} does not exist")
    if scope_type == "machine" and db.get(m.Machine, scope_id) is None:
        raise HTTPException(422, f"Machine {scope_id} does not exist")


def _out(init: m.SavingsInitiative) -> dict:
    d = SavingsOut.model_validate(init).model_dump(mode="json")
    d["evidence"] = json.loads(init.evidence_json or "{}")
    return d


@router.get("/savings")
def list_savings(db: DB):
    rows = list(db.scalars(select(m.SavingsInitiative).order_by(m.SavingsInitiative.id.desc())))
    return dict(items=[_out(r) for r in rows],
                totals={s: round(sum((r.calculated_savings or 0) for r in rows if r.evidence_status == s), 2) for s in ("estimated", "verified")}
                | {s: round(sum((r.expected_savings or 0) for r in rows if r.evidence_status == s), 2) for s in ("identified", "forecast")} | {})


@router.post("/savings", status_code=201)
def create_savings(body: SavingsCreate, db: DB):
    _scope_exists(db, body.scope_type, body.scope_id)
    init = m.SavingsInitiative(**body.model_dump())
    db.add(init)
    db.flush()
    S.evaluate(db, init)
    db.commit()
    return _out(init)


@router.get("/savings/{sid}")
def get_savings(sid: int, db: DB):
    init = db.get(m.SavingsInitiative, sid)
    if init is None:
        raise HTTPException(404, "Initiative not found")
    return _out(init)


@router.patch("/savings/{sid}")
def patch_savings(sid: int, body: SavingsPatch, db: DB):
    init = db.get(m.SavingsInitiative, sid)
    if init is None:
        raise HTTPException(404, "Initiative not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(init, k, v)
    for a, b, label in ((init.baseline_start, init.baseline_end, "baseline"), (init.post_start, init.post_end, "post-intervention")):
        if a and b and a > b:
            raise HTTPException(422, f"{label} start must not be after its end")
    _scope_exists(db, init.scope_type, init.scope_id)
    S.evaluate(db, init)
    db.commit()
    return _out(init)


@router.post("/savings/{sid}/evaluate")
def evaluate_savings(sid: int, db: DB):
    init = db.get(m.SavingsInitiative, sid)
    if init is None:
        raise HTTPException(404, "Initiative not found")
    S.evaluate(db, init)
    db.commit()
    return _out(init)


@router.delete("/savings/{sid}", status_code=204)
def delete_savings(sid: int, db: DB):
    init = db.get(m.SavingsInitiative, sid)
    if init is None:
        raise HTTPException(404, "Initiative not found")
    db.delete(init)
    db.commit()
