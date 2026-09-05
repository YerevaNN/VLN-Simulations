"""Package the recorded stress comparison as a self-contained static page."""
import json, shutil, statistics, sys
from pathlib import Path
root=Path(sys.argv[1]); out=Path(sys.argv[2]); out.mkdir(parents=True,exist_ok=True)
labels={
 'omni51-kit-hq':'H100 · OmniGibson Kit 5.1 HQ',
 'omni51-kit-hq-ap':'A6000 · OmniGibson Kit 5.1 HQ',
 'omni51-hq':'H100 · OmniGibson settings (legacy RT)',
 'omni51-hq-ap':'A6000 · OmniGibson settings (legacy RT)',
 'isaac-ap':'A6000 · Isaac 5.1 legacy RT',
 'behavior45-pt-ap':'A6000 · Isaac 4.5 path tracing',
 'behavior-pathtracing-ap':'A6000 · Isaac 5.1 path tracing / older settings',
 'omni51-pt-ap':'A6000 · Isaac 5.1 path tracing / latest settings'}
views={'overview':'Overview','reflection':'Reflections','transparency':'Layered transparency','thin_geometry':'Thin geometry','emission':'Emissive lighting','grazing':'Grazing angle'}
stress_views=list(views)
valley=Path(sys.argv[3]) if len(sys.argv)>3 else None
if valley:
 views.update({'valley-launch':'Valley · Launch area','valley-river':'Valley · River','valley-bridge':'Valley · Bridge','valley-forest':'Valley · Forest','valley-overview':'Valley · Overview'})
runs={}
suite_hashes=set()
for key,label in labels.items():
 m=json.loads((root/key/'manifest.json').read_text())
 frames={f['name']:f for f in m['frames']}
 runs[key]=dict(label=label,mode=m['render_mode'],median=round(statistics.median(f['seconds'] for f in m['frames']),3),job=m['slurm_job_id'],commit=m['git_commit'],captures={})
 (out/'images'/key).mkdir(parents=True,exist_ok=True)
 for view in stress_views:
  shutil.copy2(root/key/(view+'_2.png'),out/'images'/key/(view+'.png'))
  runs[key]['captures'][view]=dict(seconds=frames[view+'_2']['seconds'],mode=frames[view+'_2'].get('render_mode',m['render_mode']),job=m['slurm_job_id'])
 if valley:
  vm=json.loads((valley/key/'manifest.json').read_text())
  suite_hashes.add((vm['scene_sha256'],vm['cameras_sha256']))
  vf={f['name']:f for f in vm['frames']}
  assert len(vf)==15, (key,'incomplete valley run')
  for view in views:
   if view in stress_views:continue
   f=vf[view+'_2']; assert f['render_mode']==m['render_mode'],(key,view,'renderer mode changed')
   shutil.copy2(valley/key/(view+'_2.png'),out/'images'/key/(view+'.png'))
   runs[key]['captures'][view]=dict(seconds=f['seconds'],mode=f['render_mode'],job=vm['slurm_job_id'])
if valley:assert len(suite_hashes)==1,'Valley scene/camera mismatch'
shutil.copy2(root/'report'/'metrics.json',out/'metrics.json')
shutil.copy2(root/'report'/'omni51-pair.png',out/'preview.png')
data=json.dumps(dict(runs=runs,views=views))
page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>H100 rendering stress test · YerevaNN</title><meta name="description" content="Compare Isaac Sim 5.1 and OmniGibson rendering paths on H100 and RTX A6000 with matched scenes and cameras.">
<meta property="og:title" content="H100 rendering stress test · YerevaNN"><meta property="og:description" content="Matched images, renderer settings, and capture timings for H100 and RTX A6000."><meta property="og:image" content="https://yerevann.com/research/h100-rendering/preview.png"><meta property="og:type" content="website"><link rel="canonical" href="https://yerevann.com/research/h100-rendering/">
<style>*{box-sizing:border-box}body{margin:0;background:#10171e;color:#edf2f7;font:16px/1.6 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:28px clamp(16px,4vw,56px) 64px}a{color:#9dd8ff}nav{display:flex;justify-content:space-between;color:#9aaebb;font-size:14px}h1{font-size:clamp(30px,4vw,52px);line-height:1.15;margin:38px 0 16px;letter-spacing:-1px}h2{font-size:23px;margin-top:34px}p{max-width:1000px;color:#c6d2dd}.lead{font-size:19px}.tag{color:#89d9b1}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:25px 0 16px}select,button{font:inherit;background:#22313e;color:#fff;border:1px solid #526775;border-radius:7px;padding:10px;max-width:100%}button{cursor:pointer}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.card{background:#19252f;border:1px solid #334957;border-radius:12px;padding:14px}.card select{width:100%;font-size:15px}.card img{display:block;width:100%;height:auto;aspect-ratio:16/9;background:#05090c;margin-top:14px}.meta{font-size:13px;color:#adbfcd;margin-top:10px}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;max-width:1000px;text-align:left}th,td{border-bottom:1px solid #344551;padding:12px 14px;vertical-align:top}th{color:#a8c3d6;font-weight:500}details{margin-top:30px;border-top:1px solid #344551;padding-top:18px}summary{cursor:pointer;font-weight:600}li{margin:8px 0;color:#c6d2dd}footer{font-size:13px;color:#a2b4c1;margin-top:36px}code{font-size:.9em;color:#d9edff}@media(max-width:760px){.grid{grid-template-columns:1fr}main{padding-top:20px}nav{gap:12px}.controls button{font-size:14px}td,th{padding:9px}}</style></head><body><main>
<nav><a href="/">YerevaNN</a><span>Research experiment · 6 September 2026</span></nav>
<h1>H100 rendering stress test</h1><p class="lead">The same scene and cameras, across Isaac Sim and OmniGibson rendering configurations on H100 and RTX A6000.</p>
<p><span class="tag">Verified:</span> OmniGibson’s Kit configuration with Isaac Sim 5.1 produced all 18 RGB images and depth outputs on H100 in <code>RealTimePathTracing</code> mode. The matching A6000 images are visually close. This tests rendering, not a complete robot or household simulation.</p>
<div class="controls"><label for="view">Scene view</label><select id="view"></select><button id="hardware">H100 vs A6000</button><button id="modes">H100: legacy vs HQ</button></div>
<div class="grid"><section class="card"><select id="left" aria-label="Left rendering configuration"></select><a id="left-link" target="_blank" rel="noopener"><img id="left-image" width="640" height="360"></a><div class="meta" id="left-meta"></div></section><section class="card"><select id="right" aria-label="Right rendering configuration"></select><a id="right-link" target="_blank" rel="noopener"><img id="right-image" width="640" height="360"></a><div class="meta" id="right-meta"></div></section></div>
<p class="meta">Original 640 × 360 PNGs, with no image enhancement. Each view shows the third consecutive capture at that camera pose. Click an image to open it at full resolution. The link preserves your current comparison.</p>
<h2>What differs between the two H100 configurations?</h2><div class="table-wrap"><table><thead><tr><th></th><th>OmniGibson settings (legacy RT)</th><th>OmniGibson Kit 5.1 HQ</th></tr></thead><tbody><tr><th>Active renderer</th><td>RaytracedLighting · legacy real-time</td><td>RealTimePathTracing · real-time 2.0</td></tr><tr><th>Launch configuration</th><td>Stock Isaac launcher with OmniGibson settings. Stress runs fell back to legacy RT; valley runs select it explicitly.</td><td>OmniGibson Kit configuration, explicit mode enablement, and settings reapplied after scene opening.</td></tr><tr><th>Median H100 capture (material stress scene)</th><td>0.337 seconds</td><td>0.304 seconds</td></tr><tr><th>Transparency in the material stress scene</th><td>Sharper appearance</td><td>Frosted appearance, also seen on A6000</td></tr></tbody></table></div>
<p>Both use the same Isaac Sim 5.1 renderer software; no NVIDIA renderer modules were rewritten. The launch changes were tested together, so their individual necessity has not been isolated. A sharper image alone does not establish greater physical accuracy.</p>
<h2>Measured agreement and speed</h2><p>For the verified Kit HQ runs, mean absolute RGB difference between H100 and A6000 is <strong>0.84–2.02 levels on the 0–255 scale</strong> across the six views. The 95th percentile absolute depth difference is zero among jointly valid pixels in each view.</p><p>Median capture time is <strong>0.304 seconds on H100 versus 0.223 seconds on A6000</strong> (1.36×). Both request 16 subframes. These single-run timings include image transfer and saving; they are not native simulation FPS or a hardware-only benchmark.</p>
<details><summary>Method, limitations, and reproducibility</summary><ul><li>Asset-free USD scene: metallic surfaces, nested transparency, thin bars, emissive lighting, and colored walls. Six cameras, three consecutive captures each. USD Preview Surface opacity is not a validated physical-glass reference.</li><li>Latest OmniGibson source was pinned at <code>22d19cd2f99d6ae15dd0fb62e90363410cdd3260</code>. The exact renderer settings function runs with HQ enabled; the Kit runs also load its Isaac 5.1 experience file.</li><li>The verified Kit runs use H100 with driver 580.105.08 and RTX A6000 with driver 580.173.02. Scene, camera, and Kit-file hashes match. Every captured frame records the active real-time 2.0 mode.</li><li>Path-tracing controls request 64 subframes per view, versus 16 for real-time modes. Their capture durations are not equal-work speed comparisons.</li><li>Some earlier launches failed or changed modes. Only completed image sets appear here. Close agreement on these static views does not establish parity for physics, moving objects, other sensors, or long-running tasks.</li></ul><p><a href="https://github.com/YerevaNN/VLN-Simulations/blob/codex/h100-renderer-comparison/experiments/renderer_comparison/STRESS_RESULTS.md">Experiment report and source</a> · <a href="metrics.json">Image and depth measurements (JSON)</a></p></details>
<footer>YerevaNN · Exploratory rendering experiment. Results describe the recorded configurations and scene.</footer>
<script>const data=DATA;const el=id=>document.getElementById(id);for(const [key,name] of Object.entries(data.views)){const o=new Option(name,key);el('view').add(o)}for(const side of ['left','right'])for(const [key,run] of Object.entries(data.runs))el(side).add(new Option(run.label,key));const params=new URLSearchParams(location.hash.slice(1));el('view').value=data.views[params.get('view')]?params.get('view'):'transparency';el('left').value=data.runs[params.get('left')]?params.get('left'):'omni51-kit-hq-ap';el('right').value=data.runs[params.get('right')]?params.get('right'):'omni51-kit-hq';function render(){for(const side of ['left','right']){const key=el(side).value,r=data.runs[key],view=el('view').value,url='images/'+key+'/'+view+'.png';el(side+'-image').src=url;el(side+'-image').alt=r.label+' — '+data.views[view];el(side+'-link').href=url;el(side+'-meta').textContent='Active mode: '+r.mode+' · Median capture: '+r.median.toFixed(3)+' s · Run '+r.job}history.replaceState(null,'','#'+new URLSearchParams({view:el('view').value,left:el('left').value,right:el('right').value}))}for(const id of ['left','right','view'])el(id).onchange=render;el('hardware').onclick=()=>{el('left').value='omni51-kit-hq-ap';el('right').value='omni51-kit-hq';render()};el('modes').onclick=()=>{el('left').value='omni51-hq';el('right').value='omni51-kit-hq';render()};render();</script></main></body></html>'''.replace('DATA',data)
page=page.replace('</select><a id="left-link"','</select><div class="meta" id="left-time"></div><a id="left-link"').replace('</select><a id="right-link"','</select><div class="meta" id="right-time"></div><a id="right-link"')
page=page.replace("el(side+'-meta').textContent='Active mode: '+r.mode+' · Median capture: '+r.median.toFixed(3)+' s · Run '+r.job", "const c=r.captures[view];el(side+'-time').textContent=c.seconds.toFixed(3)+' seconds · selected capture';el(side+'-meta').textContent='Active mode: '+c.mode+' · Run '+c.job")
page=page.replace('Original 640 × 360 PNGs, with no image enhancement.', 'Original 640 × 360 PNGs, with no image enhancement. Seconds below each title measure the selected capture, including image transfer and saving; they are not simulation FPS.')
if valley:
 page=page.replace('The same scene and cameras, across Isaac Sim and OmniGibson rendering configurations on H100 and RTX A6000.', 'Six material stress views and five original drone-valley viewpoints, each rendered through all eight configurations on H100 and RTX A6000.')
 page=page.replace('<h2>Measured agreement and speed</h2>','<h2>Measured agreement and speed — material stress scene</h2>')
 page=page.replace('<li>Asset-free USD scene:', '<li>The five valley views use the unchanged original VLN valley scene and launch, river, bridge, forest, and overview cameras. Every configuration captures each pose three times; the page shows capture three.</li><li>Asset-free stress USD scene:')
(out/'index.html').write_text(page,encoding='utf-8')
print(f'Packaged {len(runs)} configurations, {len(runs)*len(views)} images at {out}')


