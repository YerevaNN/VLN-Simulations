#!/usr/bin/env bash
# Benchmark one real Natural Valley/PX4 episode using a local Isaac Sim installation.
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

PREFLIGHT_ONLY=false
if [[ "${1:-}" == "--preflight-only" && $# -eq 1 ]]; then
  PREFLIGHT_ONLY=true
elif [[ $# -ne 0 ]]; then
  echo "Usage: $0 [--preflight-only]" >&2
  exit 2
fi

fail() { echo "FAIL: $*" >&2; exit 2; }
command -v nvidia-smi >/dev/null || fail "nvidia-smi is missing (install a working NVIDIA driver)"
command -v python3 >/dev/null || fail "python3 is missing"
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || fail "Run on x86_64 Linux"

GPU_DEVICE=${GPU_DEVICE:-0}
EPISODE_ID=${EPISODE_ID:-0}
SEED=${SEED:-5200}
[[ "$GPU_DEVICE" =~ ^[0-9]+$ ]] || fail "GPU_DEVICE must be a GPU index"
ISAAC_PYTHON=${ISAAC_PYTHON:-${ISAAC_ROOT:+$ISAAC_ROOT/python.sh}}
[[ -n "$ISAAC_PYTHON" && -x "$ISAAC_PYTHON" ]] \
  || fail "Set ISAAC_ROOT to the Isaac Sim 5.1 directory, or ISAAC_PYTHON to its executable interpreter"
ISAAC_PYTHON=$(realpath "$ISAAC_PYTHON")

gpu_line=$(nvidia-smi --query-gpu=index,name,memory.total,driver_version \
  --format=csv,noheader,nounits -i "$GPU_DEVICE") || fail "GPU $GPU_DEVICE is unavailable"
echo "GPU: $gpu_line"
echo "Host: $(uname -srmo)"
echo "RAM: $(awk '/MemTotal:/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo)"
echo "Isaac Python: $ISAAC_PYTHON"

# active_gpu uses the nvidia-smi physical index; CUDA_VISIBLE_DEVICES keeps
# CUDA/PhysX on the selected GPU, where its visible index becomes zero.
export ISAAC_ACTIVE_GPU="$GPU_DEVICE"
export CUDA_VISIBLE_DEVICES="$GPU_DEVICE"
smoke_log=$(mktemp)
trap 'rm -f "$smoke_log"' EXIT
if ! "$ISAAC_PYTHON" -c \
  'import os; from isaacsim import SimulationApp; app = SimulationApp({"headless": True, "active_gpu": int(os.environ["ISAAC_ACTIVE_GPU"]), "multi_gpu": False}); app.update(); app.close()' \
  >"$smoke_log" 2>&1; then
  tail -n 40 "$smoke_log" >&2
  fail "Native Isaac Sim headless startup failed"
fi
rm -f "$smoke_log"
trap - EXIT
echo "Native Isaac Sim headless startup: PASSED"
if [[ "$PREFLIGHT_ONLY" == true ]]; then
  echo "PREFLIGHT PASSED. No PX4 mission was run."
  exit 0
fi

[[ -n "${RUNTIME_ROOT:-}" ]] || fail "Set RUNTIME_ROOT to a prepared Pegasus/PX4 runtime directory"
[[ -n "${DATA_ROOT:-}" ]] || fail "Set DATA_ROOT to writable simulation storage"
[[ -d "$RUNTIME_ROOT/PegasusSimulator/extensions/pegasus.simulator" ]] || fail "Pegasus extension missing under RUNTIME_ROOT"
[[ -x "$RUNTIME_ROOT/PX4-Autopilot/build/px4_sitl_default/bin/px4" ]] || fail "PX4 SITL binary missing or not executable"
[[ -d "$RUNTIME_ROOT/isaac-python-deps" ]] || fail "isaac-python-deps missing under RUNTIME_ROOT"
[[ -w "$DATA_ROOT" ]] || fail "DATA_ROOT is not writable"
[[ "$EPISODE_ID" =~ ^[0-9]+$ && "$SEED" =~ ^[0-9]+$ ]] || fail "EPISODE_ID and SEED must be nonnegative integers"
RUNTIME_ROOT=$(realpath "$RUNTIME_ROOT")
DATA_ROOT=$(realpath "$DATA_ROOT")
echo "Free disk at DATA_ROOT: $(df -hP "$DATA_ROOT" | awk 'NR==2 {print $4}')"

run_id="native-l40s-$(date -u +%Y%m%dT%H%M%SZ)-$$"
dataset_name="benchmark-$run_id"
run_dir="$DATA_ROOT/benchmarks/$run_id"
dataset_root="$DATA_ROOT/datasets/$dataset_name"
assets_root="$DATA_ROOT/assets/polyhaven-v2"
mkdir -p "$run_dir" "$dataset_root" "$assets_root"
echo "Run files: $run_dir"

if [[ ! -f "$assets_root/asset_manifest.json" ]]; then
  echo "Downloading the pinned Poly Haven assets (first run only)..."
  python3 "$REPO_ROOT/simulation/fetch_assets.py" --output-root "$assets_root" \
    >"$run_dir/assets.log" 2>&1 || fail "Asset download failed; see $run_dir/assets.log"
fi

export PYTHONPATH="$RUNTIME_ROOT/isaac-python-deps:$RUNTIME_ROOT/PegasusSimulator/extensions/pegasus.simulator${PYTHONPATH:+:$PYTHONPATH}"
gpu_csv="$run_dir/gpu.csv"
nvidia-smi --query-gpu=timestamp,index,utilization.gpu,memory.used,power.draw \
  --format=csv,noheader,nounits -i "$GPU_DEVICE" -l 1 >"$gpu_csv" 2>"$run_dir/gpu-monitor.log" &
monitor_pid=$!
stop_monitor() {
  kill "$monitor_pid" 2>/dev/null || true
  wait "$monitor_pid" 2>/dev/null || true
}
trap stop_monitor EXIT

start_s=$(date +%s)
echo "Running native Isaac Sim + Pegasus + PX4 episode $EPISODE_ID (seed $SEED)..."
cd "$REPO_ROOT"
if ! "$ISAAC_PYTHON" "$REPO_ROOT/simulation/generate_episode.py" \
  --scene-version v2 \
  --assets-root "$assets_root" \
  --output-root "$dataset_root" \
  --px4-dir "$RUNTIME_ROOT/PX4-Autopilot" \
  --episode-id "$EPISODE_ID" --seed "$SEED" \
  >"$run_dir/episode.log" 2>&1; then
  tail -n 40 "$run_dir/episode.log" >&2
  fail "Episode failed; full log: $run_dir/episode.log"
fi
wall_s=$(($(date +%s) - start_s))
stop_monitor
trap - EXIT

manifest="$dataset_root/episode-$(printf '%03d' "$EPISODE_ID")/manifest.json"
python3 - "$manifest" "$gpu_csv" "$wall_s" "$run_dir" <<'PY'
import csv
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
csv_path = Path(sys.argv[2])
wall = int(sys.argv[3])
run_dir = Path(sys.argv[4])
if not manifest_path.is_file():
    raise SystemExit(f"FAIL: no episode manifest at {manifest_path}")
m = json.loads(manifest_path.read_text())
required = ["px4.ulg", "mavlink.tlog", "frames.parquet", "joystick.parquet",
            "vehicle_state.parquet", "exports/10hz.jsonl"]
missing = [name for name in required if name not in m.get("files", {})
           or not (manifest_path.parent / name).is_file()]
if m.get("status") != "success" or m.get("schema_version") != "uav-poc-v2":
    raise SystemExit(f"FAIL: episode status={m.get('status')}; inspect {manifest_path}")
if missing or min(m.get("duration_s", 0), m.get("frame_count", 0),
                  m.get("action_count", 0)) <= 0:
    raise SystemExit(f"FAIL: incomplete episode (missing {missing}); inspect {manifest_path}")

samples = []
with csv_path.open(newline="") as stream:
    for row in csv.reader(stream):
        try:
            samples.append({"gpu_util_percent": float(row[2]),
                            "vram_mib": float(row[3])})
        except (ValueError, IndexError):
            pass
summary = {
    "result": "PASS: completed real native Isaac Sim + PX4 mission",
    "episode_manifest": str(manifest_path),
    "wall_seconds_including_startup": wall,
    "simulated_seconds": m["duration_s"],
    "real_time_factor": round(m["duration_s"] / wall, 3) if wall else None,
    "rgb_frames": m["frame_count"],
    "rgb_frames_per_wall_second": round(m["frame_count"] / wall, 2) if wall else None,
    "actions": m["action_count"],
    "peak_gpu_util_percent_sampled": max((x["gpu_util_percent"] for x in samples), default=None),
    "peak_vram_mib_sampled": max((x["vram_mib"] for x in samples), default=None),
    "gpu_samples": len(samples),
}
output = run_dir / "summary.json"
output.write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
print(f"GPU samples: {csv_path}\nFull simulator log: {run_dir / 'episode.log'}")
PY
