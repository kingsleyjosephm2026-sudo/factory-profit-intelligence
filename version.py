"""Data version counter (stored in simulation_state) used to invalidate in-process caches."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import SimulationState


def ensure_sim_state(session: Session) -> SimulationState:
    row = session.get(SimulationState, 1)
    if row is None:
        row = SimulationState(id=1, running=False, tick_count=0, seed=0, data_version=0, carry={})
        session.add(row)
        session.flush()
    return row


def get_version(session: Session) -> int:
    row = session.get(SimulationState, 1)
    return int(row.data_version) if row else 0


def bump_version(session: Session) -> int:
    row = ensure_sim_state(session)
    row.data_version = int(row.data_version or 0) + 1
    session.flush()
    return int(row.data_version)
