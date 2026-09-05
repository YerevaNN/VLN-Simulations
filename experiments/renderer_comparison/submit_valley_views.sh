#!/bin/bash
set -euo pipefail
base=/mnt/weka/hrant/rtx-vln-sample-20260905
cd "$base/repo"
for backend in omni51-kit-hq omni51-kit-hq-ap omni51-hq omni51-hq-ap isaac-ap behavior45-pt-ap behavior-pathtracing-ap omni51-pt-ap; do
  partition=rtx; gpu=rtx_a6000; mem=45G; node=()
  if [[ $backend == omni51-kit-hq || $backend == omni51-hq ]]; then
    partition=research; gpu=h100; mem=60G; node=(-w gpu03)
  fi
  sbatch --job-name="valley-$backend" --export=ALL,STRESS_SUITE=valley-eight -p "$partition" "${node[@]}" --gres="gpu:$gpu:1" --cpus-per-task=8 --mem="$mem" --time=00:12:00 -o "$base/logs/valley-%j.log" experiments/renderer_comparison/stress.slurm "$backend"
done
