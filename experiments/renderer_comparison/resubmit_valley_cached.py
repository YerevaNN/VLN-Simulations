"""Reuse completed, same-backend AP caches; never interrupt a running job."""
import subprocess
base='/mnt/weka/hrant/rtx-vln-sample-20260905'
jobs=[('246840','omni51-hq-ap','REUSE_CACHE_JOB=246833'),('246841','isaac-ap','REUSE_COMPARISON_CACHE=1'),('246842','behavior45-pt-ap','REUSE_COMPARISON_CACHE=1'),('246843','behavior-pathtracing-ap','REUSE_COMPARISON_CACHE=1'),('246844','omni51-pt-ap','REUSE_CACHE_JOB=246834')]
for old,backend,cache in jobs:
 state=subprocess.check_output(['squeue','-h','-j',old,'-o','%T'],text=True).strip()
 if state!='PENDING':
  print('Preserving job',old,state,flush=True); continue
 subprocess.run(['scancel',old],check=True)
 subprocess.run(['sbatch','--job-name=valley-'+backend,'--export=ALL,STRESS_SUITE=valley-eight,'+cache,'-p','rtx','--gres=gpu:rtx_a6000:1','--cpus-per-task=8','--mem=45G','--time=00:12:00','-o',base+'/logs/valley-%j.log','experiments/renderer_comparison/stress.slurm',backend],check=True)
