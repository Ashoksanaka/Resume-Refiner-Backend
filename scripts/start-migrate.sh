#!/bin/sh
set -e

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Syncing resume templates..."
python manage.py sync_templates

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Migration / bootstrap complete."
