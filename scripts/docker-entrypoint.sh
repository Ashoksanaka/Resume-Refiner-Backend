#!/bin/sh
set -e

# Named volumes are often root-owned on first mount; ensure the app user can write.
# When started as root (compose user: "0:0"), fix ownership then drop to django.
# When started as django (image default USER), skip chown and run directly.
mkdir -p /app/generated/pdfs /app/staticfiles /app/media

if [ "$(id -u)" = "0" ]; then
  chown -R django:django /app/generated /app/media
  # migrate mounts staticfiles writable; web mounts it :ro — ignore chown failure there.
  chown -R django:django /app/staticfiles 2>/dev/null || true
  exec gosu django "$@"
fi

exec "$@"
