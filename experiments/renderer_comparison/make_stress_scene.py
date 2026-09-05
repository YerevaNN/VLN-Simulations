"""Asset-free, deterministic renderer stress scene; no physics claims."""
import json
import sys
from pathlib import Path
import numpy as np
from pxr import Usd, UsdGeom, UsdShade, UsdLux, Gf, Sdf

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
stage = Usd.Stage.CreateNew(str(out/'valley.usdc'))
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1)
stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, '/World').GetPrim())
def material(name, color, roughness=.4, metallic=0., opacity=1., emission=(0,0,0)):
    m = UsdShade.Material.Define(stage, '/World/Materials/'+name)
    s = UsdShade.Shader.Define(stage, m.GetPath().AppendChild('Shader'))
    s.CreateIdAttr('UsdPreviewSurface')
    for key, value in [('diffuseColor',color),('emissiveColor',emission)]:
        s.CreateInput(key,Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*value))
    for key,value in [('roughness',roughness),('metallic',metallic),('opacity',opacity),('ior',1.5)]:
        s.CreateInput(key,Sdf.ValueTypeNames.Float).Set(value)
    m.CreateSurfaceOutput().ConnectToSource(s.ConnectableAPI(),'surface')
    return m
white=material('white',(.75,.75,.75)); red=material('red',(.8,.03,.02))
green=material('green',(.02,.7,.04)); mirror=material('mirror',(.95,.95,.95),.015,1.)
glass=material('transparent',(.7,.9,1),.03,0.,.18)
glow=material('emitter',(1,.2,.01),.2,0.,1.,(50,8,1))
black=material('black',(.015,.015,.015))
def shape(name,typ,pos,scale,mat):
    o=typ.Define(stage,'/World/'+name)
    if typ==UsdGeom.Cube:o.CreateSizeAttr(1)
    if typ==UsdGeom.Sphere:o.CreateRadiusAttr(1)
    x=UsdGeom.Xformable(o); x.AddTranslateOp().Set(Gf.Vec3d(*pos)); x.AddScaleOp().Set(Gf.Vec3f(*scale))
    UsdShade.MaterialBindingAPI.Apply(o.GetPrim()).Bind(mat)
    return o
shape('floor',UsdGeom.Cube,(0,1,-.1),(12,12,.2),white)
shape('back',UsdGeom.Cube,(0,5,2.5),(10,.15,5),white)
shape('left',UsdGeom.Cube,(-5,1,2.5),(.15,8,5),red)
shape('right',UsdGeom.Cube,(5,1,2.5),(.15,8,5),green)
shape('mirror_wall',UsdGeom.Cube,(0,4.88,2.5),(5,.025,3),mirror)
shape('chrome_ball',UsdGeom.Sphere,(-2,1,1),(1,1,1),mirror)
shape('glass_outer',UsdGeom.Sphere,(1,0,1),(1,1,1),glass)
shape('glass_inner',UsdGeom.Sphere,(1,.25,1),(.65,.65,.65),glass)
shape('behind_glass',UsdGeom.Cube,(1,1.5,1),(.6,.6,1.5),red)
shape('hot_emitter',UsdGeom.Sphere,(-.4,2.5,1.5),(.15,.15,.15),glow)
for i in range(48):
    shape('bar_%02d'%i,UsdGeom.Cube,(-3+i*.125,3,1.3),(.015,.04,2.6),black)
light=UsdLux.RectLight.Define(stage,'/World/Key')
light.CreateIntensityAttr(120000); light.CreateWidthAttr(1); light.CreateHeightAttr(1)
UsdGeom.Xformable(light).AddTranslateOp().Set(Gf.Vec3d(0,0,4.5))
stage.GetRootLayer().Save()
views=[('overview',(0,-8,3),(0,1,1.5)),('reflection',(-3,-3,2),(-1,3,1.5)),
       ('transparency',(1,-4,1.4),(1,1,1)),('thin_geometry',(0,-2,1.5),(0,3,1.3)),
       ('emission',(-.4,.3,1.7),(-.4,3,1.5)),('grazing',(4,-4,.4),(0,2,.3))]
poses=[]
for name,eye,target in views:
    matrix=np.asarray(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse()).tolist()
    for repeat in range(3):poses.append(dict(name=f'{name}_{repeat}',kind='view',matrix=matrix))
(out/'cameras.json').write_text(json.dumps(dict(width=640,height=360,focal_length=24,horizontal_aperture=36,vertical_aperture=20.25,clipping=[.05,100],poses=poses),indent=2))
