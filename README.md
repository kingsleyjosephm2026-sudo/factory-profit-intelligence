# Factory Profit Intelligence (FPI)

A locally runnable manufacturing analytics prototype that shows where a factory loses money across production, downtime, defects, inventory and energy, ranks the biggest sources, recommends actions, and tracks which claimed savings are actually verified.

> **All data is SIMULATED DEMO DATA** for a fictional company, generated with a fixed random seed. Nothing is connected to real machinery. The app has no authentication and is not production-hardened: run it locally only. This is a prototype to build on, not a deployed product, and no customer, saving or result is claimed.

## Quick start

### Option A: Docker (PostgreSQL)
```bash
cp .env.example .env          # set POSTGRES_PASSWORD
docker compose up --build
```
App http://localhost:8080 · API docs http://localhost:8000/docs
*(The compose setup was written but could not be executed in the build environment, which had no Docker daemon. See docs/TESTING.md.)*

### Option B: local development (SQLite fallback, no Docker)
Prerequisites: Python 3.12+, Node 20+.
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env        # optional; defaults work
python -m app.cli init-db      # Alembic migrations
python -m app.cli seed         # reproducible demo dataset (seed 42)
uvicorn app.main:app --reload --port 8000

# second terminal
cd frontend && npm install && npm run dev
```
App http://localhost:5173 · API docs http://localhost:8000/docs (or `./run_dev.sh`).
SQLite is a development fallback and is not PostgreSQL. Use PostgreSQL via `FPI_DATABASE_URL=postgresql+psycopg://...`.

### Tests
```bash
cd backend && python -m pytest -q      # 98 backend tests
cd frontend && npm test                # 9 frontend tests
```

### Useful commands
| Command | Purpose |
|---|---|
| `python -m app.cli init-db` | apply migrations |
| `python -m app.cli seed [--if-empty]` | generate demo data and run the recommendation rules |
| `python -m app.cli reset-db` | wipe transactional data and re-seed |
| `python -m app.cli export-samples` | write CSV templates and examples to `sample_data/` |

## What is in the app
Executive Overview · Profit Leakage · Production · Machine Downtime · Quality · Energy · Inventory · Root Cause Explorer · Recommendations · Savings Verification · Data Explorer (records, CSV import, exports, demo data) · Settings & Docs. A global filter bar (date range, line, machine, product, shift) drives every page. A live-demo bar starts, pauses, steps and resets a simulation that writes new simulated rows into the real tables.

## Replacing demo data with authorised company data
1. Download templates in Data Explorer > Import CSV (or `sample_data/`).
2. Create your machines, products and lines (reference data is currently seeded; add them with SQL or extend `datagen.create_reference`, see docs/DEPLOYMENT.md).
3. Import production, downtime, energy and inventory CSVs. Validate first; invalid rows are reported and never written.
4. Wipe the demo rows if desired (`reset-db` removes all transactional data).

## Documentation
[Architecture](docs/ARCHITECTURE.md) · [Analytics methodology](docs/ANALYTICS_METHODOLOGY.md) · [Data dictionary](docs/DATA_DICTIONARY.md) · [API](docs/API_DOCUMENTATION.md) · [Testing](docs/TESTING.md) · [Deployment](docs/DEPLOYMENT.md) · [Limitations](docs/LIMITATIONS.md) · [Roadmap](docs/ROADMAP.md)

## Troubleshooting
- *Frontend shows "Cannot reach the API"*: start the backend on port 8000; the Vite dev server proxies `/api` to it (`VITE_API_PROXY` to change).
- *"No data is loaded"*: run `python -m app.cli seed` or use Data Explorer > Demo data.
- *CORS error from another origin*: add it to `FPI_CORS_ORIGINS`.
- *Port in use*: change `--port` and `VITE_API_PROXY`.
