"""Render the unchanged VLN valley with pinned Isaac/OmniGibson settings.

This invokes OmniGibson's renderer configuration function, not its household
task/robot environment. Geometry and camera poses are shared across backends.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import shutil
import faulthandler
from types import SimpleNamespace

p = argparse.ArgumentParser()
p.add_argument('--output', required=True)
p.add_argument('--scene-dir', required=True)
p.add_argument('--assets-root', required=True)
p.add_argument('--backend', choices=['isaac-ap', 'behavior-hq', 'behavior-pathtracing'], required=True)
p.add_argument('--behavior-root')
p.add_argument('--initial-renderer')
p.add_argument('--prepare', action='store_true')
p.add_argument('--views-only', action='store_true')
p.add_argument('--quality-spp', type=int, default=4)
p.add_argument('--disable-denoiser', action='store_true')
p.add_argument('--omnigibson-experience', action='store_true')
p.add_argument('--force-render-mode', choices=['RaytracedLighting','RealTimePathTracing','PathTracing'])
a = p.parse_args()
out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
scene_dir = Path(a.scene_dir); scene_dir.mkdir(parents=True, exist_ok=True)
t0 = time.perf_counter()
if os.environ.get('STRESS_SUITE') == 'valley-eight':
    faulthandler.dump_traceback_later(120,repeat=True)
git_dir = Path(__file__).resolve().parents[2]/'.git'
head = (git_dir/'HEAD').read_text().strip()
run_commit = (git_dir/head[5:]).read_text().strip() if head.startswith('ref: ') else head
gpu_info = subprocess.check_output(['nvidia-smi','--query-gpu=uuid,name,driver_version','--format=csv'],text=True,timeout=30)
from isaacsim import SimulationApp
initial_renderer = a.force_render_mode or a.initial_renderer or ('PathTracing' if a.backend=='behavior-pathtracing' else ('RealTimePathTracing' if a.backend=='behavior-hq' else 'RayTracedLighting'))
launch_args=['--portable-root', os.environ['ISAAC_PORTABLE_ROOT'], '--/rtx/rendermode='+initial_renderer]
experience={}
experience_hash=None
if a.omnigibson_experience:
    runtime=Path(os.environ['ISAAC_PATH'])
    private=out/'experience'; (private/'apps').mkdir(parents=True,exist_ok=True)
    for folder in ['exts','extscache','extsPhysics','extsUser','extsDeprecated']:
        if (runtime/folder).exists() and not (private/folder).exists(): (private/folder).symlink_to(runtime/folder,target_is_directory=True)
    source=Path(a.behavior_root)/'OmniGibson/omnigibson/omnigibson_5_1_0.kit'
    kit=private/'apps'/source.name; shutil.copy2(source,kit)
    experience_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    os.environ['MDL_USER_PATH']=str(Path(a.behavior_root)/'OmniGibson/omnigibson/materials')
    experience={'experience':str(kit)}
    launch_args+=['--/persistent/rtx/modes/rt/enabled=true','--/persistent/rtx/modes/rt2/enabled=true','--/persistent/rtx/modes/pt/enabled=true']
app = SimulationApp({'headless': True, 'width': 640, 'height': 360,
                     'multi_gpu': False,
                     'renderer': initial_renderer,
                     'extra_args': launch_args,
                     'limit_cpu_threads': int(os.environ.get('OMP_NUM_THREADS', '8')),
                     'fast_shutdown': True}, **experience)
print('PHASE app_started', flush=True)
import carb
import numpy as np
import omni.usd
import omni.replicator.core as rep
from pxr import Usd, UsdGeom, Gf
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'simulation'))
import natural_valley

settings = carb.settings.get_settings()
applied = {}
class SettingsRecorder:
    def __getattr__(self, key):
        original = getattr(settings, key)
        if key.startswith('set'):
            def setter(path, value):
                applied[path] = value
                return original(path, value)
            return setter
        return original

behavior_hash = None
if a.backend.startswith('behavior'):
    source = Path(a.behavior_root) / 'OmniGibson/omnigibson/simulator.py'
    text = source.read_text()
    behavior_hash = hashlib.sha256(text.encode()).hexdigest()
    fn = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == '_set_renderer_settings')
    scope = {'lazy': SimpleNamespace(carb=SimpleNamespace(settings=SimpleNamespace(get_settings=lambda: SettingsRecorder()))),
             'gm': SimpleNamespace(ENABLE_HQ_RENDERING=True, ENABLE_FLATCACHE=True)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
    scope['_set_renderer_settings'](SimpleNamespace(get_rendering_dt=lambda: 1 / 60))
    if a.backend == 'behavior-pathtracing':
        for key, value in {'/rtx/rendermode': 'PathTracing', '/rtx/pathtracing/spp': a.quality_spp,
                           '/rtx/pathtracing/totalSpp': a.quality_spp * 64, '/rtx/pathtracing/maxBounces': 32,
                           '/rtx/pathtracing/optixDenoiser/enabled': not a.disable_denoiser}.items():
            SettingsRecorder().set(key, value)

if a.force_render_mode:
    SettingsRecorder().set('/rtx/rendermode',a.force_render_mode)

if a.prepare:
    omni.usd.get_context().new_stage()
    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, '/World')
    stage.SetDefaultPrim(world.GetPrim())
    info = natural_valley.build_environment(stage, 5200, a.assets_root)
    (scene_dir / 'inventory.json').write_text(json.dumps(info, indent=2))
    stage.Flatten().Export(str(scene_dir / 'valley.usdc'))
    poses = []
    views = [((0,-15,12),(90,0,7),'launch'), ((80,-28,18),(160,0,10),'river'),
             ((130,-60,32),(160,12,8),'bridge'), ((230,-45,35),(300,15,25),'upper_valley'),
             ((-80,80,45),(50,0,5),'forest'), ((35,-80,80),(210,15,20),'overview')]
    for eye, target, name in views:
        mat = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0,0,1)).GetInverse()
        poses.append({'name': name, 'kind': 'view', 'matrix': np.asarray(mat).tolist()})
    for i in range(48):
        x = 15 + i * 3.5
        eye = Gf.Vec3d(x, -22, 16 + 0.035*x)
        target = Gf.Vec3d(x+75, 3, 10 + 0.035*x)
        mat = Gf.Matrix4d().SetLookAt(eye, target, Gf.Vec3d(0,0,1)).GetInverse()
        poses.append({'name': f'flight_{i:03d}', 'kind': 'flight', 'matrix': np.asarray(mat).tolist()})
    (scene_dir / 'cameras.json').write_text(json.dumps({'width':640,'height':360,'focal_length':24,
        'horizontal_aperture':36,'vertical_aperture':20.25,'clipping':[0.1,5000], 'poses':poses}, indent=2))
else:
    omni.usd.get_context().open_stage(str(scene_dir / 'valley.usdc'))
    stage = omni.usd.get_context().get_stage()

config = json.loads((scene_dir / 'cameras.json').read_text())
print('PHASE scene_opened', flush=True)
if a.omnigibson_experience:
    for key,value in applied.items(): settings.set(key,value)
camera = UsdGeom.Camera.Define(stage, '/ComparisonCamera')
camera.CreateFocalLengthAttr(config['focal_length'])
camera.CreateHorizontalApertureAttr(config['horizontal_aperture'])
camera.CreateVerticalApertureAttr(config['vertical_aperture'])
camera.CreateClippingRangeAttr(Gf.Vec2f(*config['clipping']))
op = camera.AddTransformOp()
product = rep.create.render_product('/ComparisonCamera', (config['width'],config['height']))
rgb = rep.AnnotatorRegistry.get_annotator('rgb'); rgb.attach([product])
depth = rep.AnnotatorRegistry.get_annotator('distance_to_camera'); depth.attach([product])
for step in range(80):
    app.update()
    if step % 20 == 19: print('PHASE warmup', step + 1, settings.get('/rtx/rendermode'), flush=True)
records = []
for pose in config['poses']:
    if a.views_only and pose['kind'] != 'view': continue
    op.Set(Gf.Matrix4d(*[v for row in pose['matrix'] for v in row]))
    start = time.perf_counter()
    rep.orchestrator.step(rt_subframes=64 if pose['kind']=='view' and a.backend=='behavior-pathtracing' else 16, pause_timeline=False)
    pixels = np.asarray(rgb.get_data()).copy()
    for retry in range(8):
        if pixels.ndim == 3 and pixels.shape[:2] == (config['height'], config['width']): break
        print('WAIT_FOR_IMAGE',pose['name'],retry, pixels.shape,flush=True)
        rep.orchestrator.step(rt_subframes=16, pause_timeline=False)
        pixels = np.asarray(rgb.get_data()).copy()
    if pixels.ndim != 3 or pixels.shape[:2] != (config['height'], config['width']):
        raise RuntimeError(f'Invalid image at {pose["name"]}: {pixels.shape}')
    Image.fromarray(pixels[:,:,:3]).save(out / (pose['name']+'.png'))
    if pose['kind']=='view': np.save(out/(pose['name']+'-depth.npy'), np.asarray(depth.get_data()))
    records.append({'name':pose['name'],'seconds':time.perf_counter()-start,'mean':float(pixels[:,:,:3].mean()),
                    'std':float(pixels[:,:,:3].std()),'render_mode':settings.get('/rtx/rendermode')})
    print('CAPTURE', a.backend, records[-1], flush=True)
(out/'capture-records.json').write_text(json.dumps(records,indent=2))
print('PHASE captures_saved',flush=True)
metadata = {'backend':a.backend,'frames':records,'elapsed_s':time.perf_counter()-t0,
            'scene_sha256':hashlib.sha256((scene_dir/'valley.usdc').read_bytes()).hexdigest(),
            'cameras_sha256':hashlib.sha256((scene_dir/'cameras.json').read_bytes()).hexdigest(),
            'valley_source_sha256':hashlib.sha256(Path(natural_valley.__file__).read_bytes()).hexdigest(),
            'behavior_source_sha256':behavior_hash,'applied_settings':applied,
            'render_mode':settings.get('/rtx/rendermode'),
            'experience_sha256':experience_hash,'launch_args':launch_args,
            'gpu':gpu_info,
            'slurm_job_id':os.environ.get('SLURM_JOB_ID'),
            'git_commit':run_commit,
            'scope':'Static scene and matched camera replay; no PX4 flight or BEHAVIOR task dynamics.'}
(out/'manifest.json').write_text(json.dumps(metadata,indent=2))
print('COMPLETE', a.backend, flush=True)
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
