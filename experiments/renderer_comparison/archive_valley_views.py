"""Validate and preserve evidence for the eight-backend valley comparison."""
import hashlib,json,shutil,subprocess
from pathlib import Path
import numpy as np
from PIL import Image
base=Path('/mnt/weka/hrant/rtx-vln-sample-20260905'); root=base/'valley-eight'
out=base/'repo/experiments/renderer_comparison/results/valley-eight';out.mkdir(parents=True,exist_ok=True)
expected={'omni51-kit-hq':'RealTimePathTracing','omni51-kit-hq-ap':'RealTimePathTracing','omni51-hq':'RaytracedLighting','omni51-hq-ap':'RaytracedLighting','isaac-ap':'RaytracedLighting','behavior45-pt-ap':'PathTracing','behavior-pathtracing-ap':'PathTracing','omni51-pt-ap':'PathTracing'}
hashes=set();index=[];summary={}
for key,mode in expected.items():
 m=json.loads((root/key/'manifest.json').read_text()); assert len(m['frames'])==15,key
 hashes.add((m['scene_sha256'],m['cameras_sha256']))
 for f in m['frames']:
  assert f['render_mode']==mode,(key,f['name'],f['render_mode'])
  im=np.asarray(Image.open(root/key/(f['name']+'.png')))
  assert im.shape==(360,640,3) and im.std()>1,(key,f['name'],'invalid image')
  dep=np.load(root/key/(f['name']+'-depth.npy')).squeeze();assert dep.shape==(360,640)
 summary[key]={'job':m['slurm_job_id'],'mode':mode,'views':{f['name']:f['seconds'] for f in m['frames'] if f['name'].endswith('_2')}}
 (out/key).mkdir(exist_ok=True);shutil.copy2(root/key/'manifest.json',out/key/'manifest.json')
 for file in sorted((root/key).iterdir()):
  if file.is_file():index.append(dict(path=str(file.relative_to(base)),sha256=hashlib.sha256(file.read_bytes()).hexdigest(),bytes=file.stat().st_size))
assert len(hashes)==1,'Scene/camera mismatch'
assert next(iter(hashes))[0]==hashlib.sha256((base/'comparison/scene/valley.usdc').read_bytes()).hexdigest(),'Valley geometry changed'
(out/'artifact-index.json').write_text(json.dumps(index,indent=2));(out/'captures.json').write_text(json.dumps(summary,indent=2))
shutil.copy2(root/'scene/cameras.json',out/'cameras.json')
jobs=','.join(str(j) for j in [*range(246837,246851),246852,246853,246854])
(out/'slurm-accounting.txt').write_text(subprocess.check_output(['sacct','-j',jobs,'--format=JobID,State,Elapsed,NodeList,ExitCode','-P'],text=True))
print(json.dumps(summary,indent=2))

