#!/bin/sh
set -e
# Render (and other PaaS) set PORT dynamically; default 8000 for local Docker.
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
