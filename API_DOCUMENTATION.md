# API documentation

Interactive docs: `/docs` (Swagger) and `/redoc`. Errors use `{"detail": ...}` with 404 unknown id, 409 duplicate file or existing data, 413 too large, 415 unsupported file, 422 validation, 500 generic message (details only in the server log). Record lists return `{total, page, page_size, items}` with `page_size <= 500`. Common filters: `date_from, date_to, line_id, machine_id, product_id, shift`.

| Method | Path | Query parameters |
|---|---|---|
| GET | `/api/health` | - |
| GET | `/api/config` | - |
| GET | `/api/metrics` | - |
| GET | `/api/factories` | - |
| GET | `/api/machines` | - |
| GET | `/api/products` | - |
| GET | `/api/production` | page, page_size, sort_by, desc, machine_code, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/downtime` | page, page_size, planned, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/quality` | page, page_size, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/energy` | page, page_size, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/inventory` | page, page_size, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/maintenance` | page, page_size |
| GET | `/api/export/{dataset}` | dataset, format, by, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/dashboard/summary` | date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/dashboard/charts` | grain, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/analytics/production` | grain, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/analytics/downtime` | grain, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/analytics/quality` | grain, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/analytics/energy` | grain, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/analytics/inventory` | date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/loss/summary` | date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/loss/breakdown` | by, grain, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/loss/drilldown` | category, page, page_size, date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/rootcause` | date_from, date_to, line_id, machine_id, product_id, shift |
| GET | `/api/recommendations` | status, severity, rule_id |
| POST | `/api/recommendations/refresh` | - |
| PATCH | `/api/recommendations/{rec_id}` | rec_id |
| GET | `/api/savings` | - |
| POST | `/api/savings` | - |
| GET | `/api/savings/{sid}` | sid |
| PATCH | `/api/savings/{sid}` | sid |
| DELETE | `/api/savings/{sid}` | sid |
| POST | `/api/savings/{sid}/evaluate` | sid |
| GET | `/api/imports/templates/{dataset}` | dataset |
| POST | `/api/imports/validate` | - |
| GET | `/api/imports` | - |
| POST | `/api/imports` | - |
| POST | `/api/demo/generate` | force |
| GET | `/api/simulation` | - |
| GET | `/api/live/status` | - |
| POST | `/api/simulation/start` | - |
| POST | `/api/simulation/pause` | - |
| POST | `/api/simulation/tick` | - |
| POST | `/api/simulation/reset` | - |

_44 endpoints, generated from the live OpenAPI schema._
