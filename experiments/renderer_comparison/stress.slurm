#!/bin/bash
set -euo pipefail
base=/mnt/weka/hrant/rtx-vln-sample-20260905
backend=$1
cd "$base/repo"
export OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=1 ACCEPT_EULA=Y PRIVACY_CONSENT=Y
export XDG_CACHE_HOME="$base/cache/comparison-$backend" ISAAC_PORTABLE_ROOT="$base/cache/comparison-kit-$backend"
export LD_LIBRARY_PATH="$base/runtime/system-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OPTIX_CACHE_PATH="$base/cache/optix-$backend"
isaac="$base/runtime/isaac-sim-4.5"
export PYTHONPATH="$base/runtime/isaac45-python-deps"
render=behavior-pathtracing
if [[ $backend == isaac-ap || $backend == behavior-pathtracing-ap ]]; then
 isaac=/isaac-sim
 export PYTHONPATH="$base/runtime/isaac-python-deps"
fi
if [[ $backend == isaac-ap ]]; then render=isaac-ap; fi
exec "$isaac/python.sh" experiments/renderer_comparison/run_isaac.py --output "$base/stress/$backend" --scene-dir "$base/stress/scene" --assets-root "$base/assets/polyhaven-v2" --backend "$render" --behavior-root "$base/runtime/behavior-3.7.1-source"
