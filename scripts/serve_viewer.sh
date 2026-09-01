#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DATASET_ROOT=${DATASET_ROOT:?Set DATASET_ROOT to an episode dataset directory}
DATASET_NAME=${DATASET_NAME:-$(basename "$DATASET_ROOT")}
PORT=${PORT:-8787}
IMAGE=${VIEWER_IMAGE:-vln-simulations-viewer:latest}
CONTAINER=${VIEWER_CONTAINER:-vln-simulations-viewer}

docker build -t "$IMAGE" "$REPO_ROOT/viewer"
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Container $CONTAINER already exists; remove or rename it before redeploying." >&2
  exit 2
fi
docker run -d --name "$CONTAINER" --restart unless-stopped \
  -p "0.0.0.0:${PORT}:8787" \
  -e UAV_DATASET_NAME="$DATASET_NAME" \
  -v "$DATASET_ROOT:/data:ro" \
  "$IMAGE"

echo "viewer: http://0.0.0.0:${PORT}"
