#!/bin/sh
set -e
# PORT defaults to 8000; override when a reverse proxy or PaaS assigns a port.
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
