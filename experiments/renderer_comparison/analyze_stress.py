"""Compare all views and repeat captures; build inspectable contact sheet."""
import json,sys,shutil
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
root=Path(sys.argv[1]); out=root/'report';out.mkdir(exist_ok=True)
keys=['isaac-ap','behavior45-pt','behavior45-pt-ap','behavior-pathtracing-ap']
labels=['A6000 / 5.1 real-time','H100 / 4.5 path tracing','A6000 / 4.5 path tracing','A6000 / 5.1 path tracing']
available=[(k,l) for k,l in zip(keys,labels) if (root/k/'manifest.json').exists()]
keys,labels=map(list,zip(*available))
baseline='behavior45-pt' if 'behavior45-pt' in keys else 'behavior45-pt-ap'
manifests={k:json.loads((root/k/'manifest.json').read_text()) for k in keys}
assert len({(m['scene_sha256'],m['cameras_sha256']) for m in manifests.values()})==1
names=[f['name'] for f in manifests[keys[0]]['frames'] if f['name'].endswith('_2')]
def im(k,n):return np.asarray(Image.open(root/k/(n+'.png')),dtype=float)
metrics=[]
for n in names:
    for k in keys:
        if k==baseline:continue
        diff=np.abs(im(k,n)-im(baseline,n))
        metrics.append(dict(view=n,left=k,right=baseline,mae=float(diff.mean()),pixel_fraction_over_10=float((diff.max(axis=2)>10).mean()),p99=float(np.percentile(diff,99))))
repeats=[dict(backend=k,view=n,mae=float(np.abs(im(k,n)-im(k,n[:-1]+'1')).mean())) for k in keys for n in names]
diagnostic=[]
ref='behavior45-reference-ap'
if (root/ref/'manifest.json').exists():
    rm=json.loads((root/ref/'manifest.json').read_text())
    assert (rm['scene_sha256'],rm['cameras_sha256'])==(manifests[keys[0]]['scene_sha256'],manifests[keys[0]]['cameras_sha256'])
    for n in names:
        for k in keys:
            diagnostic.append(dict(view=n,left=k,right=ref,mae=float(np.abs(im(k,n)-im(ref,n)).mean())))
    shutil.copytree(root/ref,out/ref,dirs_exist_ok=True)
(out/'metrics.json').write_text(json.dumps(dict(pairs=metrics,repeats=repeats,diagnostic=diagnostic),indent=2))
sheet=Image.new('RGB',(640*len(keys),40+len(names)*390),'#172028');draw=ImageDraw.Draw(sheet)
font=ImageFont.load_default(size=19)
for col,(k,label) in enumerate(zip(keys,labels)):
    draw.text((col*640+8,8),label,fill='white',font=font)
    shutil.copytree(root/k,out/k,dirs_exist_ok=True)
    for row,n in enumerate(names):
        sheet.paste(Image.open(root/k/(n+'.png')),(col*640,40+row*390))
        draw.text((col*640+8,402+row*390),n,fill='white',font=font)
sheet.save(out/'comparison.jpg',quality=95)
pair=Image.new('RGB',(1280,400),'#172028'); pd=ImageDraw.Draw(pair)
for col,(k,label) in enumerate([('isaac-ap','A6000 / Isaac 5.1 real-time'),(baseline,'H100 / Isaac 4.5 path tracing' if baseline=='behavior45-pt' else 'A6000 control / Isaac 4.5 path tracing')]):
    pd.text((col*640+8,8),label,fill='white',font=font)
    pair.paste(Image.open(root/k/'transparency_2.png'),(col*640,40))
pair.save(out/'transparency-pair.png')
page='<!doctype html><meta charset="utf-8"><title>Adversarial rendering comparison</title><style>body{background:#172028;color:white;font:16px system-ui;margin:24px}img{width:100%}select{font:inherit;padding:8px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}a{color:skyblue}</style><h1>Adversarial rendering comparison</h1><p>Same scene and cameras. Mirrors, layered transparency, emission and thin bars. Third capture at each pose. Images are unmodified.</p><select id="view">'+''.join(f'<option>{n}</option>' for n in names)+'</select><div class="grid">'+''.join(f'<div><h3>{label}</h3><img data-key="{k}"></div>' for k,label in zip(keys,labels))+'</div><p><a href="metrics.json">Pixel differences and repeat stability</a> · <a href="comparison.jpg">All views</a></p><script>function render(){document.querySelectorAll("img").forEach(i=>i.src=i.dataset.key+"/"+document.querySelector("select").value+".png")}document.querySelector("select").onchange=render;render()</script>'
if 'behavior45-pt' not in keys:
    page=page.replace('<select id="view">','<p>H100 stress capture has not completed. These are A6000 controls comparing rendering modes; they are not H100 images.</p><select id="view">')
(out/'index.html').write_text(page,encoding='utf-8')
print(json.dumps(dict(pairs=metrics,repeats=repeats,diagnostic=diagnostic),indent=2))
