# Deployment

**This is a local demo.** There is no authentication, no TLS and no rate limiting. Do not expose it to the internet.

## Docker Compose (PostgreSQL)
`cp .env.example .env`, set `POSTGRES_PASSWORD`, then `docker compose up --build`. The backend container runs migrations, seeds demo data if the database is empty, then serves on :8000; nginx serves the built UI on :8080 and proxies `/api`. (Written but not executed in the build environment.)

## Local (SQLite fallback)
See README option B. The SQLite file is `backend/fpi_dev.db` (git-ignored).

## Configuration
All settings are `FPI_*` environment variables (`.env.example`): database URL, CORS origins, upload limits, simulation cadence/retention and every loss-model assumption.

## Loading your own reference data
Machines, lines and products are seeded by `datagen.create_reference`. For your own plant, replace those lists (or insert rows with SQL) before importing CSVs, because imports resolve `machine_code`, `product_sku` and `line_code` against existing rows. A reference-data import screen is on the roadmap.

## Hardening checklist before any real use
Add authentication and role-based access, TLS, per-user audit logging, rate limiting, secrets management, backups, a managed PostgreSQL, a security review, and data-governance approval for any real company data.
