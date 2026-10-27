# Architecture

```
React + TS + Tailwind + Recharts (Vite)  --/api-->  FastAPI  --> services (pandas/NumPy) --> SQLAlchemy --> PostgreSQL (or SQLite dev fallback)
                                                       |-- background simulator task (asyncio) writes simulated rows
```

**Backend** (`backend/app`): `models.py` (13 tables, constraints, indexes), `routers/` (HTTP only, validation), `services/` (all business logic: `analytics.py` loss model and aggregation, `rootcause.py`, `recommendations.py`, `savings.py`, `ingestion.py`, `simulator.py`, `datagen.py`, `finance.py` Decimal reference, `metrics_docs.py`). Alembic migration `0001_initial_schema`. `create_app(session_factory)` makes the app testable with an in-memory database.

**Data flow.** Filtered rows are loaded with one joined SELECT into pandas, enriched with per-record loss columns, then aggregated. The frontend never sends SQL; every endpoint takes a fixed, validated set of filters (dates, line, machine, product, shift, grain, sort field from an allow-list).

**Live demo.** `Simulator` advances a simulated clock 15 minutes per tick, builds one interval per machine with the same generator used for history (so coherence rules are identical), tags rows `source='simulation'`, prunes beyond `FPI_SIM_MAX_ROWS` (default 3000) and can be reset. The frontend polls `/api/live/status` every 7 s and refetches when the data version changes.

**Frontend** (`frontend/src`): `state.tsx` (filters, config, live status), `hooks.ts` (`useApi` refetches on filter/version change), `components/ui.tsx` (KPI cards with definitions, sortable/paginated tables, loading/error/empty states), 12 pages.

**Integration point for real data.** The CSV import endpoints and the `source` column are the seam: a future connector would write through `ingestion.commit` (or a streaming equivalent) with `source='sensor'`. No such integration exists today.
