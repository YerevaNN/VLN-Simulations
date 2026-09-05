"""Matched USD scene through Newton's Warp SensorTiledCamera (no Kit)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import faulthandler
import importlib
import numpy as np
from PIL import Image
from pxr import Usd, UsdGeom, Sdf, Gf
import warp as wp
import newton
from newton.sensors import SensorTiledCamera

p = argparse.ArgumentParser()
p.add_argument('--output', required=True)
p.add_argument('--scene-dir', required=True)
a = p.parse_args()
out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
scene = Path(a.scene_dir)
t0 = time.perf_counter()
run_commit = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
faulthandler.dump_traceback_later(120, repeat=True)
stage = Usd.Stage.Open(str(scene/'valley.usdc'))
# Expand USD PointInstancers, which the Newton importer does not traverse.
# Keep prototype-local transforms; instance matrices explicitly exclude them.
layer = stage.GetRootLayer()
instances = []
count = 0
for prim in list(stage.Traverse()):
    if not prim.IsA(UsdGeom.PointInstancer):
        continue
    pi = UsdGeom.PointInstancer(prim)
    targets = pi.GetPrototypesRel().GetTargets()
    copies = []
    for target in targets:
        dest = Sdf.Path(f'/__prototypes/p{len(instances)}_{len(copies)}')
        Sdf.CreatePrimInLayer(layer, dest.GetParentPath())
        Sdf.CopySpec(layer, target, layer, dest)
        copies.append(dest)
    transforms = pi.ComputeInstanceTransformsAtTime(Usd.TimeCode.Default(), Usd.TimeCode.Default(), UsdGeom.PointInstancer.ExcludeProtoXform)
    world = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    indices = list(pi.GetProtoIndicesAttr().Get())
    instances.append((str(prim.GetPath()), copies, transforms, world, indices))
for path, copies, transforms, world, indices in instances:
    stage.RemovePrim(path)
    for index, (mat, proto) in enumerate(zip(transforms, indices)):
        holder = UsdGeom.Xform.Define(stage, f'/World/Expanded/i{count}')
        holder.AddTransformOp().Set(mat * world)
        child = stage.DefinePrim(str(holder.GetPath())+'/asset')
        child.GetReferences().AddInternalReference(copies[proto])
        count += 1
print('EXPANDED_INSTANCES', count, flush=True)
wp.init()
wp.set_device('cuda:0')
builder = newton.ModelBuilder()
# Static rendering needs no mass integration. Reuse prototype-local mesh data
# across the transform-only references created above; no geometry is altered.
importer = importlib.import_module('newton._src.utils.import_usd')
original_get_mesh = importer.usd.get_mesh
mesh_cache = {}
mesh_calls = 0
def get_visual_mesh(prim, **kwargs):
    global mesh_calls
    kwargs['compute_inertia'] = False
    points = prim.GetAttribute('points')
    stack = points.GetPropertyStack() if points else []
    key = (str(stack[0].path) if stack else str(prim.GetPath()), tuple(sorted(kwargs.items())))
    if key not in mesh_cache:
        mesh_cache[key] = original_get_mesh(prim, **kwargs)
    mesh_calls += 1
    if mesh_calls % 100 == 0: print('MESH_IMPORT',mesh_calls,'unique',len(mesh_cache),flush=True)
    return mesh_cache[key]
importer.usd.get_mesh = get_visual_mesh
builder.add_usd(stage, root_path='/World', floating=False,
                load_visual_shapes=True, load_static_visual_shapes=True,
                skip_mesh_approximation=True)
print('IMPORTED_SHAPES', builder.shape_count, flush=True)
model = builder.finalize()
state = model.state()
sensor = SensorTiledCamera(model)
sensor.default_render_config.enable_shadows = True
sensor.default_render_config.enable_textures = True
sun = next(prim for prim in stage.Traverse() if prim.GetTypeName() == 'DistantLight')
direction = UsdGeom.Xformable(sun).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).TransformDir(Gf.Vec3d(0,0,-1)).GetNormalized()
sensor.utils.create_default_light(enable_shadows=True, direction=wp.vec3f(*direction))
config = json.loads((scene/'cameras.json').read_text())
w,h = config['width'],config['height']
rays = sensor.utils.compute_camera_rays_pinhole(w,h,focal_length=config['focal_length'],horizontal_aperture=config['horizontal_aperture'],vertical_aperture=config['vertical_aperture'])
color = sensor.utils.create_color_image_output(w,h,1)
depth = sensor.utils.create_depth_image_output(w,h,1)
model.bvh_refit_shapes(state)
records = []
for pose in config['poses']:
    mat = Gf.Matrix4d(*np.asarray(pose['matrix']).ravel().tolist())
    quat = mat.ExtractRotationQuat()
    transform = wp.transformf(wp.vec3f(*mat.ExtractTranslation()), wp.quatf(*quat.GetImaginary(),quat.GetReal()))
    cameras = wp.array([[transform]], dtype=wp.transformf)
    start = time.perf_counter()
    sensor.update(state,cameras,rays,color_image=color,depth_image=depth)
    wp.synchronize()
    pixels = sensor.utils.to_rgba_from_color(color).numpy().reshape(h,w,4)[:,:,:3]
    Image.fromarray(pixels).save(out/(pose['name']+'.png'))
    if pose['kind']=='view': np.save(out/(pose['name']+'-depth.npy'),depth.numpy().reshape(h,w))
    records.append({'name':pose['name'],'seconds':time.perf_counter()-start,'mean':float(pixels.mean()),'std':float(pixels.std())})
    print('CAPTURE',records[-1],flush=True)
metadata = {'backend':'newton-warp','frames':records,'elapsed_s':time.perf_counter()-t0,
    'expanded_instances':count,'shape_count':model.shape_count,
    'scene_sha256':hashlib.sha256((scene/'valley.usdc').read_bytes()).hexdigest(),
    'cameras_sha256':hashlib.sha256((scene/'cameras.json').read_bytes()).hexdigest(),
    'git_commit':run_commit,
    'newton_commit':subprocess.check_output(['git','-C',str(Path(newton.__file__).parents[1]),'rev-parse','HEAD'],text=True).strip(),
    'slurm_job_id':os.environ.get('SLURM_JOB_ID'),
    'gpu':subprocess.check_output(['nvidia-smi','--query-gpu=name,uuid,driver_version','--format=csv'],text=True),
    'limitations':['Direct Newton SensorTiledCamera backend, not full Isaac Lab task execution.',
      'Directional sun orientation matched; default Newton illumination, no matched HDRI or radiometric intensity.',
      'USD material support is determined by Newton importer; not a claim of RTX feature parity.',
      'Static scene/camera replay, no flight dynamics.']}
(out/'manifest.json').write_text(json.dumps(metadata,indent=2))
