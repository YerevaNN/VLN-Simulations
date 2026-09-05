#!/bin/bash
set -uo pipefail
cd /mnt/weka/hrant/rtx-vln-sample-20260905/repo
export STRESS_SUITE=valley-eight RENDER_TIMEOUT=900
result=0
for backend in omni51-kit-hq omni51-hq; do
 export REUSE_CACHE_JOB=246837
 [[ $backend != omni51-hq ]] || export REUSE_CACHE_JOB=246845
 bash experiments/renderer_comparison/stress.slurm "$backend" || result=$?
done
exit "$result"
