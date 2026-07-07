#!/bin/sh
# Run Django API + Celery worker + Celery beat in one container (Render free tier).
# Render does not offer free background-worker services or preDeployCommand, so
# migrations and all processes run at container start (~512MB RAM).
set -e

echo "[start] Running database migrations..."
python manage.py migrate --noinput

echo "[start] Syncing LaTeX templates to database..."
python manage.py sync_templates

echo "[start] Starting Celery worker..."
celery -A config worker -l info -Q celery,resume_generation,maintenance --concurrency=1 &
WORKER_PID=$!

echo "[start] Starting Celery beat..."
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler &
BEAT_PID=$!

cleanup() {
  kill "$WORKER_PID" "$BEAT_PID" 2>/dev/null || true
  wait "$WORKER_PID" "$BEAT_PID" 2>/dev/null || true
}
trap cleanup TERM INT

echo "[start] Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 1 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
