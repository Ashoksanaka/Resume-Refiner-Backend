#!/bin/sh
# Ensure the shared Docker network exists so frontend/backend can start in either order.
set -e
NETWORK_NAME="${RESUME_REFINER_NETWORK:-resume-refiner-net}"

if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
  echo "Network $NETWORK_NAME already exists"
  exit 0
fi

docker network create "$NETWORK_NAME"
echo "Created network $NETWORK_NAME"
