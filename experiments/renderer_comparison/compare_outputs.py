"""Report paired image/depth differences; these are not general fidelity scores."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image
p=argparse.ArgumentParser();p.add_argument('--results',required=True);p.add_argument('--output',required=True)
a=p.parse_args();root=Path(a.results)
pairs=[('isaac-ap','newton'),('behavior-pathtracing-ap','behavior45-pt'),('behavior45-pt-ap','behavior45-pt')]
result=[]
for left,right in pairs:
    if not (root/left/'manifest.json').exists() or not (root/right/'manifest.json').exists(): continue
    lm=json.loads((root/left/'manifest.json').read_text());rm=json.loads((root/right/'manifest.json').read_text())
    assert lm['scene_sha256']==rm['scene_sha256'] and lm['cameras_sha256']==rm['cameras_sha256']
    for f in lm['frames'][:6]:
        name=f['name']
        l=np.asarray(Image.open(root/left/(name+'.png')),dtype=np.float32)
        r=np.asarray(Image.open(root/right/(name+'.png')),dtype=np.float32)
        ld=np.load(root/left/(name+'-depth.npy')).squeeze();rd=np.load(root/right/(name+'-depth.npy')).squeeze()
        # Compare near/midrange geometry, excluding misses and the different far clips.
        mask=np.isfinite(ld)&np.isfinite(rd)&(ld>0)&(rd>0)&(ld<500)&(rd<500)
        diff=np.abs(ld[mask]-rd[mask])
        result.append({'left':left,'right':right,'view':name,'rgb_mae_0_255':float(np.abs(l-r).mean()),
          'compared_depth_pixel_fraction':float(mask.mean()),'depth_abs_median_m':float(np.median(diff)),
          'depth_abs_p95_m':float(np.percentile(diff,95)),
          'depth_within_10cm_fraction':float((diff<0.1).mean())})
Path(a.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
