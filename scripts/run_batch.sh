#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RUNTIME_ROOT=${RUNTIME_ROOT:?Set RUNTIME_ROOT to the prepared Pegasus/PX4 runtime directory}
DATA_ROOT=${DATA_ROOT:?Set DATA_ROOT to the bulk UAV simulation storage directory}
ISAAC_IMAGE=${ISAAC_IMAGE:-nvcr.io/nvidia/isaac-sim:5.1.0}
GPU_DEVICE=${GPU_DEVICE:-0}
DATASET_NAME=${DATASET_NAME:-natural-valley-v2}
EPISODE_START=${EPISODE_START:-0}
EPISODE_END=${EPISODE_END:-9}
SEED_BASE=${SEED_BASE:-5200}
MAX_ATTEMPTS=${MAX_ATTEMPTS:-3}

DATASET_ROOT="$DATA_ROOT/datasets/$DATASET_NAME"
ASSETS_ROOT="$DATA_ROOT/assets/polyhaven-v2"
LOG_ROOT="$DATA_ROOT/logs/$DATASET_NAME"
mkdir -p "$DATASET_ROOT" "$ASSETS_ROOT" "$LOG_ROOT"

for required in \
  "$RUNTIME_ROOT/PegasusSimulator/extensions/pegasus.simulator" \
  "$RUNTIME_ROOT/PX4-Autopilot/build/px4_sitl_default/bin/px4" \
  "$RUNTIME_ROOT/isaac-python-deps"; do
  if [[ ! -e "$required" ]]; then
    echo "Missing runtime dependency: $required" >&2
    exit 2
  fi
done

if [[ ! -f "$ASSETS_ROOT/asset_manifest.json" ]]; then
  python3 "$REPO_ROOT/simulation/fetch_assets.py" --output-root "$ASSETS_ROOT"
fi

episode_is_complete() {
  local episode_id=$1
  local manifest="$DATASET_ROOT/episode-$(printf '%03d' "$episode_id")/manifest.json"
  python3 - "$manifest" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(1)
manifest = json.loads(path.read_text())
raise SystemExit(0 if manifest.get("status") == "success" and manifest.get("schema_version") == "uav-poc-v2" else 1)
PY
}

run_episode() {
  local episode_id=$1 seed=$2 attempt=$3
  local episode_name="episode-$(printf '%03d' "$episode_id")"
  docker run --rm --user root --gpus "device=$GPU_DEVICE" --network=host \
    -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y \
    -e PYTHONPATH=/runtime/isaac-python-deps:/runtime/PegasusSimulator/extensions/pegasus.simulator \
    -v "$REPO_ROOT:/workspace/repo:ro" \
    -v "$RUNTIME_ROOT:/runtime" \
    -v "$DATA_ROOT:/data" \
    -v "$DATA_ROOT/isaac-cache/ov:/root/.cache/ov" \
    -v "$DATA_ROOT/isaac-cache/glcache:/root/.cache/nvidia/GLCache" \
    -v "$DATA_ROOT/isaac-cache/computecache:/root/.nv/ComputeCache" \
    --entrypoint /isaac-sim/python.sh "$ISAAC_IMAGE" \
    /workspace/repo/simulation/generate_episode.py \
    --scene-version v2 \
    --assets-root /data/assets/polyhaven-v2 \
    --output-root "/data/datasets/$DATASET_NAME" \
    --px4-dir /runtime/PX4-Autopilot \
    --episode-id "$episode_id" --seed "$seed" \
    >"$LOG_ROOT/${episode_name}-attempt-${attempt}.log" 2>&1
}

for episode_id in $(seq "$EPISODE_START" "$EPISODE_END"); do
  if episode_is_complete "$episode_id"; then
    echo "episode $episode_id already complete"
    continue
  fi
  seed=$((SEED_BASE + episode_id))
  completed=false
  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    echo "running episode $episode_id seed $seed attempt $attempt"
    run_episode "$episode_id" "$seed" "$attempt" || true
    if episode_is_complete "$episode_id"; then
      completed=true
      break
    fi
    tail -n 30 "$LOG_ROOT/episode-$(printf '%03d' "$episode_id")-attempt-${attempt}.log"
  done
  if [[ "$completed" != true ]]; then
    echo "episode $episode_id failed after $MAX_ATTEMPTS attempts" >&2
    exit 3
  fi
done

docker run --rm --user root \
  -e PYTHONPATH=/runtime/isaac-python-deps \
  -v "$REPO_ROOT:/workspace/repo:ro" \
  -v "$RUNTIME_ROOT:/runtime:ro" \
  -v "$DATA_ROOT:/data" \
  --entrypoint /isaac-sim/python.sh "$ISAAC_IMAGE" \
  /workspace/repo/simulation/validate_dataset.py "/data/datasets/$DATASET_NAME" \
  --expected $((EPISODE_END - EPISODE_START + 1))

docker run --rm --user root -v "$DATA_ROOT:/data" alpine:3.22 \
  chown -R "$(id -u):$(id -g)" "/data/datasets/$DATASET_NAME"

echo "validated dataset: $DATASET_ROOT"
