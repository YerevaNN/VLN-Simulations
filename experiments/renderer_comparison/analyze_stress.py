"""Compare all views and repeat captures; build inspectable contact sheet."""
import json,sys,shutil
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
root=Path(sys.argv[1]); out=root/'report';out.mkdir(exist_ok=True)
keys=['isaac-ap','behavior45-pt','behavior45-pt-ap','behavior-pathtracing-ap']
labels=['A6000 / 5.1 real-time','H100 / 4.5 path tracing','A6000 / 4.5 path tracing','A6000 / 5.1 path tracing']
manifests={k:json.loads((root/k/'manifest.json').read_text()) for k in keys}
assert len({(m['scene_sha256'],m['cameras_sha256']) for m in manifests.values()})==1
names=[f['name'] for f in manifests[keys[0]]['frames'] if f['name'].endswith('_2')]
def im(k,n):return np.asarray(Image.open(root/k/(n+'.png')),dtype=float)
metrics=[]
for n in names:
    for k in [keys[0],keys[2],keys[3]]:
        diff=np.abs(im(k,n)-im(keys[1],n))
        metrics.append(dict(view=n,left=k,right=keys[1],mae=float(diff.mean()),pixel_fraction_over_10=float((diff.max(axis=2)>10).mean()),p99=float(np.percentile(diff,99))))
repeats=[dict(backend=k,view=n,mae=float(np.abs(im(k,n)-im(k,n[:-1]+'1')).mean())) for k in keys for n in names]
(out/'metrics.json').write_text(json.dumps(dict(pairs=metrics,repeats=repeats),indent=2))
sheet=Image.new('RGB',(2560,40+len(names)*390),'#172028');draw=ImageDraw.Draw(sheet)
font=ImageFont.load_default(size=19)
for col,(k,label) in enumerate(zip(keys,labels)):
    draw.text((col*640+8,8),label,fill='white',font=font)
    shutil.copytree(root/k,out/k,dirs_exist_ok=True)
    for row,n in enumerate(names):
        sheet.paste(Image.open(root/k/(n+'.png')),(col*640,40+row*390))
        draw.text((col*640+8,402+row*390),n,fill='white',font=font)
sheet.save(out/'comparison.jpg',quality=95)
page='<!doctype html><meta charset="utf-8"><title>Adversarial rendering comparison</title><style>body{background:#172028;color:white;font:16px system-ui;margin:24px}img{width:100%}select{font:inherit;padding:8px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}a{color:skyblue}</style><h1>Adversarial rendering comparison</h1><p>Same scene and cameras. Mirrors, layered transparency, emission and thin bars. Third capture at each pose. Images are unmodified.</p><select id="view">'+''.join(f'<option>{n}</option>' for n in names)+'</select><div class="grid">'+''.join(f'<div><h3>{label}</h3><img data-key="{k}"></div>' for k,label in zip(keys,labels))+'</div><p><a href="metrics.json">Pixel differences and repeat stability</a> · <a href="comparison.jpg">All views</a></p><script>function render(){document.querySelectorAll("img").forEach(i=>i.src=i.dataset.key+"/"+document.querySelector("select").value+".png")}document.querySelector("select").onchange=render;render()</script>'
(out/'index.html').write_text(page)
print(json.dumps(dict(pairs=metrics,repeats=repeats),indent=2))
