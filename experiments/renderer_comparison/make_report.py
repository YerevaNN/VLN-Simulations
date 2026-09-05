"""Build a local visual comparison from verified render output directories."""
import argparse
import html
import json
from pathlib import Path
import shutil
from PIL import Image, ImageDraw, ImageFont

p=argparse.ArgumentParser()
p.add_argument('--results',required=True)
p.add_argument('--output',required=True)
a=p.parse_args()
root=Path(a.results); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
labels={'isaac-ap':'Isaac Sim 5.1 · AP / RTX A6000',
        'newton':'Newton / Warp · H100',
        'behavior45':'BEHAVIOR 3.7.1 / Isaac 4.5 · H100',
        'behavior45-pt':'BEHAVIOR 3.7.1 / path tracing · H100',
        'behavior-pathtracing-ap':'Matched path tracing · AP / RTX A6000',
        'behavior-pathtracing':'BEHAVIOR / Isaac 5.1 path tracing · H100',
        'behavior-hq':'BEHAVIOR / Isaac 5.1 real-time · H100'}
backends={}
for folder,label in labels.items():
    manifest=root/folder/'manifest.json'
    if not manifest.exists(): continue
    m=json.loads(manifest.read_text())
    if len(m['frames'])!=54: continue
    for f in m['frames']:
        file=root/folder/(f['name']+'.png')
        with Image.open(file) as im:
            assert im.size==(640,360),file
            im.verify()
    target=out/folder; target.mkdir(exist_ok=True)
    for file in (root/folder).glob('*.png'): shutil.copy2(file,target/file.name)
    shutil.copy2(manifest,target/'manifest.json')
    backends[folder]={'label':label,'manifest':m}
assert 'isaac-ap' in backends
hashes={(b['manifest']['scene_sha256'],b['manifest']['cameras_sha256']) for b in backends.values()}
assert len(hashes)==1, 'Scene/camera mismatch across runs'
frames=[f['name'] for f in backends['isaac-ap']['manifest']['frames']]
default=['isaac-ap','newton' if 'newton' in backends else 'newton-unavailable',next((b for b in ['behavior45','behavior45-pt','behavior-pathtracing','behavior-hq'] if b in backends),'unavailable')]
data=json.dumps({'backends':backends,'frames':frames,'default':default})
page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Valley rendering comparison</title><style>
body{font:16px system-ui;background:#13191e;color:#e9eef2;margin:28px}h1{font-size:28px}p{max-width:1100px;line-height:1.5;color:#bbc7ce}
.controls{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:24px 0}button,select{font:inherit;padding:9px;background:#24323b;color:white;border:1px solid #49616d;border-radius:6px}input{width:min(600px,65vw)}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}article{background:#1c262d;border-radius:10px;padding:12px}article img{width:100%;display:block;margin:14px 0}article select{width:100%;font-size:14px}.placeholder{aspect-ratio:16/9;display:grid;place-items:center;text-align:center;background:#262c31;padding:16px}.meta{font-size:13px;color:#a6b9c4;line-height:1.6}a{color:#92d5ed}details{margin-top:26px}pre{white-space:pre-wrap;font-size:12px}@media(max-width:900px){.grid{grid-template-columns:1fr}}
</style><h1>Same valley, different rendering paths</h1>
<p>Six fixed views and a 48-frame camera replay. Every completed run uses the same scene and camera poses at 640 × 360. This is a rendering comparison; the camera replay does not simulate drone flight.</p>
<div class="controls"><button id="play">Play camera replay</button><input id="frame" type="range" min="0" max="53" value="0"><strong id="caption"></strong></div><div class="grid" id="grid"></div>
<p>Newton uses its own lighting and material support, so this is not a claim of RTX-equivalent quality. Use a column selector to inspect the matching path-tracing control on AP. A missing result means no valid image was obtained, not a black rendered scene.</p>
<details><summary>Provenance and settings</summary><pre id="provenance"></pre></details>
<script>const data=DATA;const slider=document.querySelector('#frame');let timer;
for(let i=0;i<3;i++){const card=document.createElement('article');const options=Object.entries(data.backends).map(([k,v])=>`<option value="${k}">${v.label}</option>`).join('');card.innerHTML=`<select>${options}<option value="unavailable">No completed H100 Kit render</option><option value="newton-unavailable">No completed Newton render</option></select><div class="picture"></div><div class="meta"></div>`;card.querySelector('select').value=data.default[i];card.querySelector('select').onchange=render;document.querySelector('#grid').append(card)}
function render(){const n=Number(slider.value),name=data.frames[n];document.querySelector('#caption').textContent=n<6?`Fixed view ${n+1} of 6`:`Camera replay ${n-5} / 48`;for(const card of document.querySelectorAll('article')){const key=card.querySelector('select').value,b=data.backends[key];card.querySelector('.picture').innerHTML=b?`<img src="${key}/${name}.png" alt="${b.label}, ${name}">`:'<div class="placeholder">No valid frame produced.<br>See the experiment report for startup and capture failures.</div>';card.querySelector('.meta').innerHTML=b?`Job ${b.manifest.slurm_job_id} · <a href="${key}/manifest.json">Run manifest</a><br>${key==='newton'?'Warp rendering; simpler lighting/material model':b.manifest.render_mode}`:''}}
slider.oninput=render;document.querySelector('#play').onclick=()=>{if(timer){clearInterval(timer);timer=null;document.querySelector('#play').textContent='Play camera replay';return}if(Number(slider.value)<6)slider.value=6;timer=setInterval(()=>{slider.value=Number(slider.value)>=53?6:Number(slider.value)+1;render()},125);document.querySelector('#play').textContent='Pause'};document.querySelector('#provenance').textContent=JSON.stringify(data.backends,null,2);render();</script></html>'''.replace('DATA',data)
(out/'index.html').write_text(page,encoding='utf-8')
sheet=Image.new('RGB',(1920,800),'#13191e');draw=ImageDraw.Draw(sheet)
font=ImageFont.load_default(size=20)
for col,key in enumerate(default):
    title=labels.get(key,'H100 Kit: no completed render')
    draw.text((col*640+12,10),title,fill='white',font=font)
    for row,name in enumerate([frames[0],frames[5]]):
        file=root/key/(name+'.png')
        if file.exists():
            with Image.open(file) as im:sheet.paste(im,(col*640,40+row*380))
        else:draw.text((col*640+20,180+row*380),'No valid image produced',fill='white',font=font)
sheet.save(out/'comparison.png')
print(json.dumps({'report':str(out/'index.html'),'completed_backends':list(backends)},indent=2))
