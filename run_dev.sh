#!/usr/bin/env bash
# Non-Docker development start (SQLite fallback). Run from the project root.
set -euo pipefail
( cd backend && pip install -r requirements-dev.txt && python -m app.cli init-db && python -m app.cli seed --if-empty && uvicorn app.main:app --reload --port 8000 ) &
( cd frontend && npm install && npm run dev ) &
wait
