#!/bin/bash
set -euo pipefail
base=/mnt/weka/hrant/rtx-vln-sample-20260905
backend=$1
cd "$base/repo"
export OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=1 ACCEPT_EULA=Y PRIVACY_CONSENT=Y
export XDG_CACHE_HOME="$base/cache/stress-${SLURM_JOB_ID}-$backend" ISAAC_PORTABLE_ROOT="$base/cache/stress-kit-${SLURM_JOB_ID}-$backend"
export LD_LIBRARY_PATH="$base/runtime/system-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OPTIX_CACHE_PATH="$base/cache/stress-optix-${SLURM_JOB_ID}-$backend"
mkdir -p "$XDG_CACHE_HOME" "$ISAAC_PORTABLE_ROOT" "$OPTIX_CACHE_PATH"
isaac="$base/runtime/isaac-sim-4.5"
export PYTHONPATH="$base/runtime/isaac45-python-deps"
render=behavior-pathtracing
behavior_root="$base/runtime/behavior-3.7.1-source"
if [[ $backend == isaac-ap || $backend == behavior-pathtracing-ap ]]; then
 isaac=/isaac-sim
 export PYTHONPATH="$base/runtime/isaac-python-deps"
fi
if [[ $backend == isaac-ap ]]; then render=isaac-ap; fi
if [[ $backend == omni51-* ]]; then
 isaac="$base/runtime/isaac-sim"
 [[ $backend != *-ap ]] || isaac=/isaac-sim
 export PYTHONPATH="$base/runtime/isaac-python-deps"
 behavior_root="$base/runtime/BEHAVIOR-1K"
 render=behavior-hq
 [[ $backend != omni51-pt* ]] || render=behavior-pathtracing
fi
suite=${STRESS_SUITE:-stress-bright}
extra=()
if [[ $backend == behavior45-reference-ap ]]; then extra=(--quality-spp 64 --disable-denoiser); fi
exec timeout --signal=TERM --kill-after=15s 600s "$isaac/python.sh" experiments/renderer_comparison/run_isaac.py --output "$base/$suite/$backend" --scene-dir "$base/$suite/scene" --assets-root "$base/assets/polyhaven-v2" --backend "$render" --behavior-root "$behavior_root" "${extra[@]}"
