# Testing

```bash
cd backend && python -m pytest -q     # in-memory SQLite, fixed-seed data, never touches fpi_dev.db
cd frontend && npm test && npx tsc --noEmit
```

## Backend (pytest) coverage
| Area | File |
|---|---|
| Financial calculations, Decimal vs vectorised agreement, no double counting, margin-not-revenue, scrap-cost model | `test_finance_and_analytics.py` |
| Defect rate, zero production, empty data, previous-period comparison, planned vs unplanned downtime, MTBF/MTTR, energy cost, filters | `test_finance_and_analytics.py` |
| Dataset shape, fixed-seed reproducibility, internal coherence, planted patterns | `test_datagen.py` |
| Recommendation triggers, required fields, idempotent refresh, status/notes persistence, API validation | `test_recommendations.py` |
| Savings maths, every verification gate, manual numbers never verified, API cannot force "verified" | `test_savings.py` |
| CSV import: valid, bad rows, duplicates (file and database), same-file guard, all-or-nothing, dry run, size/encoding/binary/extension, rollback on database failure, all four datasets, templates | `test_ingestion.py` |
| API: shapes, filters change values, input validation (422), pagination, sorting, loss/root-cause endpoints and limitations, exports incl. formula-injection guard, empty database, generic 500, CORS, simulation tick/reset/retention/start/pause and background loop | `test_api_and_simulator.py` |

## Frontend (Vitest + Testing Library)
KPI card values/differences/"n/a" percentage handling, table sorting and pagination, empty state, number formatting and tone logic.

## Manual browser verification performed during the build (Playwright, real servers)
All 12 pages load with 0 console errors and 0 failed requests; global filters change KPIs; definition popover; live step/resume/pause/reset; recommendation status and notes persist across reload; savings initiative creation; CSV validation shows rejected rows; no horizontal scroll at 390 px. These scripts are not part of the repository's automated suite.

## Not tested
PostgreSQL and Docker (no database server or Docker daemon was available in the build environment); the migration was generated and applied on SQLite only. Load/performance beyond ~10k rows; accessibility audit with assistive technology; Safari/Firefox.
