#!/usr/bin/env bash
# Production deploy on the AWS VM: pull the prebuilt image and restart the stack.
# Invoked by the GitHub Actions deploy workflow over SSH (or manually).
#
# Required env:
#   BACKEND_IMAGE   Fully-qualified image ref, e.g. ghcr.io/owner/repo:<sha>
# Optional env:
#   COMPOSE_FILE    Compose file (default: docker-compose.prod.yml)
#   GHCR_USER       Registry username for private image pulls
#   GHCR_TOKEN      Registry token for private image pulls
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
: "${BACKEND_IMAGE:?BACKEND_IMAGE must be set (e.g. ghcr.io/owner/repo:<sha>)}"

if [ ! -f .env ]; then
  echo "ERROR: .env not found in $(pwd). Create it from .env.example before deploying." >&2
  exit 1
fi

if [ -n "${GHCR_TOKEN:-}" ] && [ -n "${GHCR_USER:-}" ]; then
  echo "Authenticating to ghcr.io as ${GHCR_USER}..."
  echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin
fi

export BACKEND_IMAGE
echo "Deploying image: ${BACKEND_IMAGE}"

docker compose -f "${COMPOSE_FILE}" pull
docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans
docker image prune -f

echo "Waiting for the stack to become healthy..."
for _ in $(seq 1 24); do
  if curl -fsS http://localhost/healthz >/dev/null 2>&1; then
    echo "Health check passed."
    docker compose -f "${COMPOSE_FILE}" ps
    exit 0
  fi
  sleep 5
done

echo "ERROR: health check did not pass in time." >&2
docker compose -f "${COMPOSE_FILE}" ps
docker compose -f "${COMPOSE_FILE}" logs --tail=50 web nginx || true
exit 1
