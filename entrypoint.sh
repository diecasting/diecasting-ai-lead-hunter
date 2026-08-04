#!/usr/bin/env bash
# Container entrypoint: wait for the database, create tables, then start the API.
set -euo pipefail

echo "[entrypoint] Initializing database schema..."
python scripts/init_db.py

echo "[entrypoint] Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
