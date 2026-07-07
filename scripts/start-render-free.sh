#!/bin/sh
# Run Django API + Celery worker + Celery beat in one container (Render free tier).
# Render does not offer free background-worker services, so all processes share
# the single free web service (~512MB RAM — keep concurrency low).
set -e

celery -A config worker -l info -Q celery,resume_generation,maintenance --concurrency=1 &
WORKER_PID=$!

celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler &
BEAT_PID=$!

cleanup() {
  kill "$WORKER_PID" "$BEAT_PID" 2>/dev/null || true
  wait "$WORKER_PID" "$BEAT_PID" 2>/dev/null || true
}
trap cleanup TERM INT

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 1 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
