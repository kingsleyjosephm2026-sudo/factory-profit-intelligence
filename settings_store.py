"""Runtime-editable loss-model assumptions (persisted in app_settings)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import DEFAULT_ASSUMPTIONS
from app.db.models import AppSetting

KEY = "assumptions"

# (min, max) validation for every assumption
LIMITS: dict[str, tuple[float, float]] = {
    "target_unplanned_downtime_pct": (0.0, 50.0),
    "downtime_sellable_share": (0.0, 1.0),
    "energy_tolerance_pct": (0.0, 100.0),
    "target_process_waste_pct": (0.0, 50.0),
    "inventory_carrying_rate_pct": (0.0, 100.0),
    "slow_moving_days_of_cover": (1.0, 3650.0),
    "savings_realization_factor": (0.0, 1.0),
    "anomaly_robust_z": (1.0, 20.0),
}


def get_assumptions(session: Session) -> dict[str, Any]:
    row = session.get(AppSetting, KEY)
    merged = dict(DEFAULT_ASSUMPTIONS)
    if row and isinstance(row.value, dict):
        merged.update({k: v for k, v in row.value.items() if k in DEFAULT_ASSUMPTIONS})
    return merged


def validate_assumptions(values: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in values.items():
        if k not in LIMITS:
            raise ValueError(f"Unknown assumption '{k}'")
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"Assumption '{k}' must be a number")
        lo, hi = LIMITS[k]
        if not (lo <= fv <= hi):
            raise ValueError(f"Assumption '{k}' must be between {lo} and {hi}")
        out[k] = fv
    return out


def set_assumptions(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    clean = validate_assumptions(values)
    current = get_assumptions(session)
    current.update(clean)
    row = session.get(AppSetting, KEY)
    if row is None:
        session.add(AppSetting(key=KEY, value=current))
    else:
        row.value = current
    session.flush()
    return current


def reset_assumptions(session: Session) -> dict[str, Any]:
    row = session.get(AppSetting, KEY)
    if row is not None:
        session.delete(row)
        session.flush()
    return dict(DEFAULT_ASSUMPTIONS)
