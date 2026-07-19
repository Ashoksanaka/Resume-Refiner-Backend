#!/bin/sh
set -e

# Fail fast with a clear message if Supabase/Postgres is unreachable.
python - <<'PY'
import os, re, sys
from urllib.parse import urlparse

def scrub(s: str) -> str:
    return re.sub(r":([^:@/]+)@", ":***@", s)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
try:
    import django
    django.setup()
    from django.db import connection
    connection.ensure_connection()
except Exception as e:
    msg = scrub(str(e).split("\n")[0])[:240]
    print("ERROR: Database connection failed before migrate.")
    print(msg)
    print("Update DIRECT_URL / POSTGRES_* in .env with a valid Supabase session URI, then restart.")
    sys.exit(1)

host = None
direct = os.environ.get("DIRECT_URL") or ""
if direct:
    host = urlparse(direct).hostname
print(f"Database OK ({host or os.environ.get('POSTGRES_HOST') or 'configured'})")
PY

echo "Running migrations..."
python manage.py migrate --noinput

echo "Syncing resume templates..."
python manage.py sync_templates

echo "Starting Django development server..."
exec python manage.py runserver 0.0.0.0:8000
