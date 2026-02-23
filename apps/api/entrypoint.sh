#!/bin/sh
set -e

# Run migrations before starting the API (idempotent).
alembic upgrade head

workers="${API_UVICORN_WORKERS:-4}"
if [ "$workers" -lt 1 ] 2>/dev/null; then
  workers=1
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "$workers"
