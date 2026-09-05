#!/bin/bash
# Submit with explicit partition and GRES; all runs use Slurm allocation.
set -euo pipefail
base=${VLN_COMPARISON_ROOT:?Set VLN_COMPARISON_ROOT outside source control}
backend=${1:?isaac-ap, behavior-hq, behavior-pathtracing, or newton}
cd "$base/repo"
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-8} OPENBLAS_NUM_THREADS=1
export ACCEPT_EULA=Y PRIVACY_CONSENT=Y
export XDG_CACHE_HOME="$base/cache/comparison-$backend"
export ISAAC_PORTABLE_ROOT="$base/cache/comparison-kit-$backend"
export LD_LIBRARY_PATH="$base/runtime/system-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OPTIX_CACHE_PATH="$base/cache/optix-$backend"
mkdir -p "$OPTIX_CACHE_PATH"
mkdir -p "$XDG_CACHE_HOME" "$ISAAC_PORTABLE_ROOT" "$base/comparison/$backend"
args=(--output "$base/comparison/$backend" --scene-dir "$base/comparison/scene")
if [[ $backend == newton ]]; then
  exec "$base/runtime/h100-python/bin/python" experiments/renderer_comparison/run_newton.py "${args[@]}"
else
  isaac="$base/runtime/isaac-sim"
  [[ $backend != isaac-ap ]] || isaac=/isaac-sim
  render_backend=$backend
  if [[ $backend == behavior-pathtracing-ap ]]; then isaac=/isaac-sim; render_backend=behavior-pathtracing; fi
  export PYTHONPATH="$base/runtime/isaac-python-deps${PYTHONPATH:+:$PYTHONPATH}"
  extra=()
  if [[ $backend == isaac-ap && ! -f "$base/comparison/scene/cameras.json" ]]; then extra+=(--prepare); fi
  exec "$isaac/python.sh" experiments/renderer_comparison/run_isaac.py "${args[@]}" \
    --assets-root "$base/assets/polyhaven-v2" --backend "$render_backend" \
    --behavior-root "$base/runtime/BEHAVIOR-1K" "${extra[@]}"
fi
