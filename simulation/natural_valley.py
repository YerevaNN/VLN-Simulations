"""High-fidelity natural valley scene and ten distinct UAV missions for dataset v2."""

import json
import math
from pathlib import Path

import numpy as np
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdPhysics, UsdShade


ASSET_IDS = {
    "boulder": "boulder_01",
    "dead_log": "dead_tree_trunk",
    "fern": "fern_02",
    "fir": "fir_sapling",
    "grass": "grass_bermuda_01",
    "mature_tree": "jacaranda_tree",
    "cliff": "mountainside",
    "pine": "pine_sapling_small",
    "rock": "rock_07",
    "small_rock": "rock_09",
    "moss_rocks": "rock_moss_set_01",
    "shrub": "shrub_02",
    "stone": "stone_01",
    "stump": "tree_stump_01",
}


def river_y(x):
    return 7.0 * math.sin(x / 70.0) + 3.0 * math.sin(x / 31.0)


def terrain_height(x, y, seed):
    """Mountain valley height field with a navigable river corridor and distant ridges."""
    centre = river_y(x)
    lateral = abs(y - centre)
    # Cap the large-scale terms outside the high-detail terrain.  This keeps the
    # same near-field valley while allowing a several-kilometre visual terrain
    # skirt without numerical mountain spikes at its boundary.
    ridge = 0.0015 * min(lateral, 900.0) ** 1.78
    ridged_detail = (1.0 - math.exp(-lateral / 70.0)) * (
        3.1 * math.sin(x / 47.0 + seed * 0.013)
        + 2.0 * math.sin((x + y) / 31.0)
        + 1.2 * math.cos((x - 2.0 * y) / 19.0)
    )
    river_cut = -1.1 * math.exp(-((y - centre) / 8.0) ** 2)
    saddle = -7.0 * math.exp(-((x - 220.0) / 75.0) ** 2 - ((y - 78.0) / 38.0) ** 2)
    upstream_rise = 0.00085 * min(max(0.0, x - 255.0), 600.0) ** 2
    horizon_distance = max(0.0, max(abs(x), abs(y)) - 650.0)
    horizon_rise = min(95.0, 0.055 * horizon_distance)
    base = ridge + ridged_detail + river_cut + saddle + upstream_rise + horizon_rise
    launch_blend = min(1.0, math.hypot(x, y) / 24.0)
    return max(-1.2, base * (0.12 + 0.88 * launch_blend))


def asset_path(assets_root, key):
    asset_id = ASSET_IDS[key]
    return str(Path(assets_root) / "models" / asset_id / f"{asset_id}_1k.usdc")


def texture_path(assets_root, texture_id, channel):
    root = Path(assets_root) / "textures" / texture_id
    matches = sorted(root.glob(f"{channel}.*"))
    if not matches:
        raise FileNotFoundError(f"Missing {texture_id}/{channel} in {assets_root}")
    return str(matches[0])


def create_pbr_material(stage, path, assets_root, texture_id, uv_scale=1.0, opacity=1.0):
    material = UsdShade.Material.Define(stage, path)
    surface = UsdShade.Shader.Define(stage, f"{path}/Surface")
    surface.CreateIdAttr("UsdPreviewSurface")
    surface.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.82)
    surface.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    surface.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
    st_reader = UsdShade.Shader.Define(stage, f"{path}/TexCoord")
    st_reader.CreateIdAttr("UsdPrimvarReader_float2")
    st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    transform = UsdShade.Shader.Define(stage, f"{path}/Transform2d")
    transform.CreateIdAttr("UsdTransform2d")
    transform.CreateInput("in", Sdf.ValueTypeNames.Float2).ConnectToSource(
        st_reader.ConnectableAPI(), "result"
    )
    transform.CreateInput("scale", Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(uv_scale, uv_scale))
    for channel, input_name, output_name in (
        ("diffuse", "diffuseColor", "rgb"),
        ("normal", "normal", "rgb"),
        ("roughness", "roughness", "r"),
    ):
        try:
            filename = texture_path(assets_root, texture_id, channel)
        except FileNotFoundError:
            continue
        texture = UsdShade.Shader.Define(stage, f"{path}/{channel.title()}Texture")
        texture.CreateIdAttr("UsdUVTexture")
        texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(filename)
        texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            transform.ConnectableAPI(), "result"
        )
        texture.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("repeat")
        texture.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("repeat")
        texture.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
        texture.CreateOutput("r", Sdf.ValueTypeNames.Float)
        surface.CreateInput(input_name, {
            "diffuseColor": Sdf.ValueTypeNames.Color3f,
            "normal": Sdf.ValueTypeNames.Normal3f,
            "roughness": Sdf.ValueTypeNames.Float,
        }[input_name]).ConnectToSource(texture.ConnectableAPI(), output_name)
    surface.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), "surface")
    return material


def create_asset_material(stage, path, assets_root, asset_id):
    root = Path(assets_root) / "models" / asset_id / "textures"
    alpha_files = sorted(root.glob("*_alpha_*"))
    diffuse_files = sorted(root.glob("*_diff_*"))
    if alpha_files:
        alpha_stem = alpha_files[0].name.replace("_alpha_", "_diff_")
        matching_diffuse = root / alpha_stem
        if matching_diffuse.exists():
            diffuse_files = [matching_diffuse]
    channels = {
        "diffuse": diffuse_files,
        "normal": sorted(root.glob("*_nor_gl_*")),
        "roughness": sorted(root.glob("*_rough_*")),
    }
    if not channels["diffuse"]:
        raise FileNotFoundError(f"No model textures for {asset_id}")
    material = UsdShade.Material.Define(stage, path)
    surface = UsdShade.Shader.Define(stage, f"{path}/Surface")
    surface.CreateIdAttr("UsdPreviewSurface")
    surface.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.82)
    surface.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    st_reader = UsdShade.Shader.Define(stage, f"{path}/TexCoord")
    st_reader.CreateIdAttr("UsdPrimvarReader_float2")
    st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    for channel, input_name, output_name in (
        ("diffuse", "diffuseColor", "rgb"),
        ("normal", "normal", "rgb"),
        ("roughness", "roughness", "r"),
    ):
        if not channels[channel]:
            continue
        texture = UsdShade.Shader.Define(stage, f"{path}/{channel.title()}Texture")
        texture.CreateIdAttr("UsdUVTexture")
        texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(str(channels[channel][0]))
        texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            st_reader.ConnectableAPI(), "result"
        )
        texture.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("repeat")
        texture.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("repeat")
        texture.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
        texture.CreateOutput("r", Sdf.ValueTypeNames.Float)
        surface.CreateInput(input_name, {
            "diffuseColor": Sdf.ValueTypeNames.Color3f,
            "normal": Sdf.ValueTypeNames.Normal3f,
            "roughness": Sdf.ValueTypeNames.Float,
        }[input_name]).ConnectToSource(texture.ConnectableAPI(), output_name)
    if alpha_files:
        alpha = UsdShade.Shader.Define(stage, f"{path}/AlphaTexture")
        alpha.CreateIdAttr("UsdUVTexture")
        alpha.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(str(alpha_files[0]))
        alpha.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            st_reader.ConnectableAPI(), "result"
        )
        alpha.CreateOutput("r", Sdf.ValueTypeNames.Float)
        surface.CreateInput("opacity", Sdf.ValueTypeNames.Float).ConnectToSource(
            alpha.ConnectableAPI(), "r"
        )
        surface.CreateInput("opacityThreshold", Sdf.ValueTypeNames.Float).Set(0.28)
    surface.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), "surface")
    return material


def create_color_material(stage, path, color, roughness=0.5, opacity=1.0, metallic=0.0):
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Surface")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
    shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
    shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return material


def bind(prim, material, strong=False):
    strength = UsdShade.Tokens.strongerThanDescendants if strong else UsdShade.Tokens.weakerThanDescendants
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material, strength)


def create_mesh(stage, path, points, indices, counts, uvs=None, material=None, collision=False):
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(points)
    mesh.CreateFaceVertexIndicesAttr(indices)
    mesh.CreateFaceVertexCountsAttr(counts)
    mesh.CreateSubdivisionSchemeAttr().Set("none")
    mesh.CreateExtentAttr(UsdGeom.Mesh.ComputeExtent(points))
    if uvs:
        primvar = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
            "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.vertex
        )
        primvar.Set(uvs)
    if material:
        bind(mesh.GetPrim(), material)
    if collision:
        UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
    return mesh


def build_terrain(stage, seed, assets_root):
    grid_n = 161
    extent = 650.0
    coordinates = np.linspace(-extent, extent, grid_n)
    points, uvs = [], []
    for y in coordinates:
        for x in coordinates:
            points.append(Gf.Vec3f(float(x), float(y), float(terrain_height(x, y, seed))))
            uvs.append(Gf.Vec2f(float((x + extent) / 28.0), float((y + extent) / 28.0)))
    indices, counts = [], []
    for row in range(grid_n - 1):
        for column in range(grid_n - 1):
            a = row * grid_n + column
            b, c, d = a + 1, a + grid_n, a + grid_n + 1
            indices.extend([a, b, d, a, d, c])
            counts.extend([3, 3])
    ground = create_pbr_material(
        stage, "/World/Materials/Ground", assets_root, "aerial_grass_rock"
    )
    create_mesh(stage, "/World/Terrain", points, indices, counts, uvs, ground, collision=True)
    return ground


def build_distant_terrain(stage, seed, ground_material):
    """Build a coarse visual terrain ring that hides the finite scene boundary."""
    grid_n = 161
    extent = 2400.0
    coordinates = np.linspace(-extent, extent, grid_n)
    points, uvs = [], []
    for y in coordinates:
        for x in coordinates:
            points.append(Gf.Vec3f(float(x), float(y), float(terrain_height(x, y, seed) - 0.5)))
            uvs.append(Gf.Vec2f(float((x + extent) / 34.0), float((y + extent) / 34.0)))
    indices, counts = [], []
    for row in range(grid_n - 1):
        for column in range(grid_n - 1):
            x0, x1 = coordinates[column], coordinates[column + 1]
            y0, y1 = coordinates[row], coordinates[row + 1]
            # Leave a hole under the high-detail collision mesh, retaining a
            # narrow overlap at its edge so no background can leak through.
            if max(abs(x0), abs(x1), abs(y0), abs(y1)) < 620.0:
                continue
            a = row * grid_n + column
            b, c, d = a + 1, a + grid_n, a + grid_n + 1
            indices.extend([a, b, d, a, d, c])
            counts.extend([3, 3])
    create_mesh(
        stage, "/World/DistantTerrain", points, indices, counts, uvs,
        ground_material, collision=False,
    )


def ribbon_geometry(samples, half_width, z_offset, seed, y_function=river_y):
    points, uvs, indices, counts = [], [], [], []
    for i, x in enumerate(samples):
        y = y_function(float(x))
        z = terrain_height(float(x), y, seed) + z_offset
        points.extend([
            Gf.Vec3f(float(x), float(y - half_width), float(z)),
            Gf.Vec3f(float(x), float(y + half_width), float(z)),
        ])
        uvs.extend([Gf.Vec2f(i / 5.0, 0.0), Gf.Vec2f(i / 5.0, 1.0)])
    for i in range(len(samples) - 1):
        a = 2 * i
        indices.extend([a, a + 1, a + 3, a, a + 3, a + 2])
        counts.extend([3, 3])
    return points, indices, counts, uvs


def build_river(stage, seed, assets_root):
    # Continue the river well beyond every route so it never terminates inside
    # the camera frustum as the aircraft advances up-valley.
    samples = np.linspace(-1200.0, 1600.0, 281)
    riverbed_material = create_pbr_material(
        stage, "/World/Materials/Riverbed", assets_root, "ganges_river_pebbles"
    )
    geometry = ribbon_geometry(samples, 7.2, 0.12, seed)
    create_mesh(stage, "/World/Riverbed", *geometry, riverbed_material, collision=False)
    water_material = create_color_material(
        stage, "/World/Materials/Water", (0.001, 0.018, 0.032), roughness=0.13, opacity=0.58
    )
    geometry = ribbon_geometry(samples, 2.6, 0.23, seed)
    create_mesh(stage, "/World/RiverWater", *geometry, water_material, collision=False)


def point_instancer(stage, path, prototype_specs, instances):
    """Create efficient metric OpenUSD instances."""
    # Prototype roots must be descendants of the PointInstancer.  When they
    # are authored as siblings, Hydra also traverses and renders each source
    # asset once at its local origin, which stacked vegetation on the pad.
    instancer = UsdGeom.PointInstancer.Define(stage, path)
    prototype_paths = []
    for index, (asset, base_scale, material) in enumerate(prototype_specs):
        prototype_path = f"{path}/Prototypes/P{index}"
        prototype = UsdGeom.Xform.Define(stage, prototype_path)
        prototype.GetPrim().GetReferences().AddReference(asset)
        prototype.AddScaleOp().Set(Gf.Vec3f(base_scale, base_scale, base_scale))
        bind(prototype.GetPrim(), material, strong=True)
        prototype_paths.append(Sdf.Path(prototype_path))
    instancer.CreatePrototypesRel().SetTargets(prototype_paths)
    instancer.CreateProtoIndicesAttr([item[0] for item in instances])
    instancer.CreatePositionsAttr([Gf.Vec3f(*item[1]) for item in instances])
    instancer.CreateOrientationsAttr([
        Gf.Quath(float(math.cos(item[2] * 0.5)), Gf.Vec3h(0.0, 0.0, float(math.sin(item[2] * 0.5))))
        for item in instances
    ])
    instancer.CreateScalesAttr([Gf.Vec3f(*item[3]) for item in instances])
    if instances:
        positions = np.asarray([item[1] for item in instances], dtype=float)
        max_scale = max(max(item[3]) for item in instances)
        margin = max(12.0, 12.0 * max_scale)
        lower = positions.min(axis=0) - margin
        upper = positions.max(axis=0) + margin
        instancer.CreateExtentAttr([
            Gf.Vec3f(*lower.astype(float)), Gf.Vec3f(*upper.astype(float))
        ])
    return instancer


def safe_from_landmarks(x, y):
    landmarks = [(0, 0), (72, river_y(72)), (145, 8), (180, -55), (130, 85), (260, river_y(260))]
    return all(math.hypot(x - lx, y - ly) > 12.0 for lx, ly in landmarks)


def clear_of_launch(x, y, radius):
    """Keep oversized visual assets outside the shared takeoff/landing clearing."""
    return math.hypot(x, y) >= radius


def scatter_nature(stage, seed, assets_root):
    rng = np.random.default_rng(seed)
    materials = {
        key: create_asset_material(stage, f"/World/Materials/Asset_{key}", assets_root, asset_id)
        for key, asset_id in ASSET_IDS.items()
    }
    route_segments = []
    for episode_id in range(10):
        route = mission_definition(episode_id, 5200 + episode_id)["waypoints_enu_m"]
        route_segments.extend(zip(route, route[1:]))

    def clear_of_routes(x, y, clearance):
        point = np.asarray([x, y], dtype=float)
        for start, end in route_segments:
            a = np.asarray(start[:2], dtype=float)
            b = np.asarray(end[:2], dtype=float)
            delta = b - a
            fraction = float(np.clip(np.dot(point - a, delta) / max(np.dot(delta, delta), 1e-6), 0.0, 1.0))
            if float(np.linalg.norm(point - (a + fraction * delta))) < clearance:
                return False
        return True
    trees, distant_trees, mature_trees, groundcover, rocks, debris = [], [], [], [], [], []
    for _ in range(520):
        x = float(rng.uniform(-310, 390))
        centre = river_y(x)
        side = float(rng.choice([-1, 1]))
        y = centre + side * float(rng.uniform(25, 205))
        if (not safe_from_landmarks(x, y) or not clear_of_launch(x, y, 80.0)
                or not clear_of_routes(x, y, 35.0)):
            continue
        z = terrain_height(x, y, seed)
        prototype = int(rng.integers(0, 2))
        scale = float(rng.uniform(1.5, 3.0))
        trees.append((prototype, (x, y, z), float(rng.uniform(-math.pi, math.pi)), (scale, scale, scale)))
    for _ in range(145):
        x = float(rng.uniform(-300, 390))
        centre = river_y(x)
        y = centre + float(rng.choice([-1, 1])) * float(rng.uniform(48, 190))
        if (not safe_from_landmarks(x, y) or not clear_of_launch(x, y, 90.0)
                or not clear_of_routes(x, y, 45.0)):
            continue
        z = terrain_height(x, y, seed)
        scale = float(rng.uniform(0.30, 0.50))
        mature_trees.append((0, (x, y, z), float(rng.uniform(-math.pi, math.pi)), (scale, scale, scale)))
    for _ in range(950):
        x = float(rng.uniform(-290, 370))
        centre = river_y(x)
        y = centre + float(rng.choice([-1, 1])) * float(rng.uniform(10, 155))
        if not clear_of_launch(x, y, 60.0):
            continue
        z = terrain_height(x, y, seed)
        prototype = int(rng.integers(0, 3))
        scale = float(rng.uniform((1.2, 0.7, 0.35)[prototype], (2.8, 1.8, 0.95)[prototype]))
        groundcover.append((prototype, (x, y, z + 0.04), float(rng.uniform(-math.pi, math.pi)), (scale, scale, scale)))
    for _ in range(380):
        x = float(rng.uniform(-280, 380))
        centre = river_y(x)
        bank_distance = float(rng.choice([-1, 1])) * float(rng.uniform(4.5, 28.0))
        y = centre + bank_distance
        if not clear_of_launch(x, y, 40.0):
            continue
        z = terrain_height(x, y, seed)
        prototype = int(rng.integers(0, 4))
        scale = float(rng.uniform(0.45, 2.2))
        rocks.append((prototype, (x, y, z + 0.08), float(rng.uniform(-math.pi, math.pi)), (scale, scale, scale)))
    for _ in range(55):
        x = float(rng.uniform(-230, 340))
        y = river_y(x) + float(rng.choice([-1, 1])) * float(rng.uniform(18, 120))
        if not clear_of_launch(x, y, 60.0):
            continue
        z = terrain_height(x, y, seed)
        prototype = int(rng.integers(0, 2))
        scale = float(rng.uniform(0.7, 1.4))
        debris.append((prototype, (x, y, z), float(rng.uniform(-math.pi, math.pi)), (scale, scale, scale)))
    # Lower-density background forest masks the near-field scatter boundary and
    # gives the valley a stable silhouette throughout every mission.
    for _ in range(1200):
        x = float(rng.uniform(-1200, 1600))
        centre = river_y(x)
        y = centre + float(rng.choice([-1, 1])) * float(rng.uniform(300, 850))
        z = terrain_height(x, y, seed)
        prototype = int(rng.integers(0, 2))
        scale = float(rng.uniform(1.5, 3.4))
        distant_trees.append((
            prototype, (x, y, z), float(rng.uniform(-math.pi, math.pi)),
            (scale, scale, scale),
        ))
    point_instancer(stage, "/World/Nature/Trees", [
        (asset_path(assets_root, "fir"), 1.0, materials["fir"]),
        (asset_path(assets_root, "pine"), 1.0, materials["pine"]),
    ], trees)
    point_instancer(stage, "/World/Nature/DistantTrees", [
        (asset_path(assets_root, "fir"), 1.0, materials["fir"]),
        (asset_path(assets_root, "pine"), 1.0, materials["pine"]),
    ], distant_trees)
    point_instancer(stage, "/World/Nature/MatureTrees", [
        (asset_path(assets_root, "mature_tree"), 1.0, materials["mature_tree"]),
    ], mature_trees)
    point_instancer(stage, "/World/Nature/Groundcover", [
        (asset_path(assets_root, "grass"), 1.0, materials["grass"]),
        (asset_path(assets_root, "fern"), 1.0, materials["fern"]),
        (asset_path(assets_root, "shrub"), 1.0, materials["shrub"]),
    ], groundcover)
    point_instancer(stage, "/World/Nature/Rocks", [
        (asset_path(assets_root, "small_rock"), 1.0, materials["small_rock"]),
        (asset_path(assets_root, "stone"), 1.0, materials["stone"]),
        (asset_path(assets_root, "rock"), 1.0, materials["rock"]),
        (asset_path(assets_root, "boulder"), 1.0, materials["boulder"]),
    ], rocks)
    point_instancer(stage, "/World/Nature/Debris", [
        (asset_path(assets_root, "stump"), 1.0, materials["stump"]),
        (asset_path(assets_root, "dead_log"), 1.0, materials["dead_log"]),
    ], debris)
    return {
        "tree_instances": len(trees) + len(mature_trees),
        "distant_tree_instances": len(distant_trees),
        "groundcover_instances": len(groundcover),
        "river_stone_instances": len(rocks),
        "debris_instances": len(debris),
    }


def cube(stage, path, position, scale, material, rotation_z=0.0):
    prim = UsdGeom.Cube.Define(stage, path)
    prim.CreateSizeAttr(1.0)
    prim.AddTranslateOp().Set(Gf.Vec3d(*position))
    prim.AddRotateZOp().Set(rotation_z)
    prim.AddScaleOp().Set(Gf.Vec3f(*scale))
    bind(prim.GetPrim(), material)
    UsdPhysics.CollisionAPI.Apply(prim.GetPrim())
    return prim


def cylinder(stage, path, position, radius, height, material):
    prim = UsdGeom.Cylinder.Define(stage, path)
    prim.CreateRadiusAttr(radius)
    prim.CreateHeightAttr(height)
    prim.AddTranslateOp().Set(Gf.Vec3d(*position))
    bind(prim.GetPrim(), material)
    UsdPhysics.CollisionAPI.Apply(prim.GetPrim())
    return prim


def build_landmarks(stage, seed, assets_root):
    wood = create_color_material(stage, "/World/Materials/Wood", (0.20, 0.095, 0.035), 0.76)
    canvas = create_color_material(stage, "/World/Materials/Canvas", (0.42, 0.17, 0.06), 0.9)
    marker = create_color_material(stage, "/World/Materials/Marker", (0.92, 0.22, 0.05), 0.42)
    stone = create_color_material(stage, "/World/Materials/CairnStone", (0.36, 0.34, 0.30), 0.93)
    rock_material = create_asset_material(
        stage, "/World/Materials/LandmarkRock", assets_root, ASSET_IDS["rock"]
    )
    boulder_material = create_asset_material(
        stage, "/World/Materials/LandmarkBoulder", assets_root, ASSET_IDS["boulder"]
    )
    cliff_material = create_asset_material(
        stage, "/World/Materials/LandmarkCliff", assets_root, ASSET_IDS["cliff"]
    )
    # Timber footbridge crossing the river at x=72 m.
    bx, by = 72.0, river_y(72.0)
    bz = terrain_height(bx, by, seed) + 2.1
    for i in range(13):
        cube(stage, f"/World/Landmarks/Footbridge/Plank_{i:02d}",
             (bx, by - 6.0 + i, bz), (3.2, 0.43, 0.12), wood)
    for side_name, side in (("West", -1), ("East", 1)):
        cube(stage, f"/World/Landmarks/Footbridge/Rail_{side_name}",
             (bx - side * 2.7, by, bz + 1.0), (0.09, 6.5, 0.09), wood)
    # Stone cairn landmark.
    cx, cy = 180.0, -55.0
    cz = terrain_height(cx, cy, seed)
    for layer, (count, radius) in enumerate(((10, 4.3), (7, 3.0), (4, 1.7), (1, 0.0))):
        for i in range(count):
            angle = 2 * math.pi * i / max(1, count)
            cylinder(stage, f"/World/Landmarks/Cairn/L{layer}_{i}",
                     (cx + radius * math.cos(angle), cy + radius * math.sin(angle), cz + 0.55 + layer * 1.0),
                     0.75 if layer < 2 else 0.6, 1.0, stone)
    # Fire lookout tower and orange survey marker.
    lx, ly = 130.0, 85.0
    lz = terrain_height(lx, ly, seed)
    for post_index, (dx, dy) in enumerate(((-2.3, -2.3), (-2.3, 2.3), (2.3, -2.3), (2.3, 2.3))):
        cube(stage, f"/World/Landmarks/Lookout/Post_{post_index}",
             (lx + dx, ly + dy, lz + 4.5), (0.16, 0.16, 4.5), wood)
    cube(stage, "/World/Landmarks/Lookout/Deck", (lx, ly, lz + 8.8), (3.2, 3.2, 0.2), wood)
    cube(stage, "/World/Landmarks/Lookout/Cabin", (lx, ly, lz + 10.5), (2.4, 2.4, 1.5), canvas)
    cylinder(stage, "/World/Landmarks/Lookout/Beacon", (lx, ly, lz + 13.2), 0.25, 2.2, marker)
    # Waterfall at the upper river and a visible plunge pool.
    wx, wy = 260.0, river_y(260.0)
    wz = terrain_height(wx, wy, seed)
    waterfall = UsdGeom.Cube.Define(stage, "/World/Landmarks/Waterfall/Sheet")
    waterfall.CreateSizeAttr(1.0)
    waterfall.AddTranslateOp().Set(Gf.Vec3d(wx + 2.0, wy, wz + 5.0))
    waterfall.AddScaleOp().Set(Gf.Vec3f(0.35, 4.2, 5.0))
    bind(waterfall.GetPrim(), create_color_material(
        stage, "/World/Materials/Waterfall", (0.20, 0.64, 0.72), 0.12, 0.68
    ))
    # Rockslide on the north slope and cliff gate on the south side.
    slide = []
    rng = np.random.default_rng(seed + 991)
    for _ in range(34):
        x = float(rng.uniform(195, 242)); y = float(rng.uniform(58, 92)); z = terrain_height(x, y, seed)
        scale = float(rng.uniform(1.8, 5.0))
        slide.append((int(rng.integers(0, 2)), (x, y, z), float(rng.uniform(-math.pi, math.pi)), (scale, scale, scale)))
    point_instancer(stage, "/World/Landmarks/Rockslide", [
        (asset_path(assets_root, "rock"), 1.0, rock_material),
        (asset_path(assets_root, "boulder"), 1.0, boulder_material),
    ], slide)
    valley_walls = []
    for i in range(18):
        x = 125.0 + i * 25.0
        side = -1.0 if i % 2 else 1.0
        y = river_y(x) + side * (150.0 + 18.0 * math.sin(i * 1.7))
        z = terrain_height(x, y, seed) - 2.5
        scale = 2.8 + 0.45 * (i % 5)
        valley_walls.append((0, (x, y, z), float(-0.7 + i * 0.63), (scale, scale, scale)))
    point_instancer(stage, "/World/Landmarks/ValleyWalls", [
        (asset_path(assets_root, "cliff"), 1.0, cliff_material),
    ], valley_walls)
    for i, (x, y) in enumerate(((285.0, -70.0), (294.0, -57.0))):
        prim = UsdGeom.Xform.Define(stage, f"/World/Landmarks/CliffGate/C{i}")
        prim.GetPrim().GetReferences().AddReference(asset_path(assets_root, "cliff"))
        prim.AddTranslateOp().Set(Gf.Vec3d(x, y, terrain_height(x, y, seed)))
        prim.AddRotateZOp().Set(-20.0 + i * 35.0)
        prim.AddScaleOp().Set(Gf.Vec3f(1.35, 1.35, 1.35))
        bind(prim.GetPrim(), cliff_material, strong=True)


def build_lighting(stage, seed, assets_root):
    sky = UsdLux.DomeLight.Define(stage, "/World/Sky")
    sky.CreateIntensityAttr(680.0)
    sky.CreateTextureFileAttr().Set(str(
        Path(assets_root) / "hdri/drakensberg_solitary_mountain/drakensberg_solitary_mountain_2k.hdr"
    ))
    sky.CreateTextureFormatAttr().Set(UsdLux.Tokens.latlong)
    sky.AddRotateXYZOp().Set(Gf.Vec3f(0.0, 0.0, float(15 + (seed % 7) * 8)))
    sun = UsdLux.DistantLight.Define(stage, "/World/Sun")
    sun.CreateIntensityAttr(float(1050 + 75 * (seed % 4)))
    sun.CreateAngleAttr(0.65)
    sun.CreateColorAttr(Gf.Vec3f(1.0, 0.91, 0.76))
    sun.AddRotateXYZOp().Set(Gf.Vec3f(42.0, -22.0, float(28 + 13 * (seed % 5))))


def build_environment(stage, seed, assets_root):
    manifest_path = Path(assets_root) / "asset_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Asset manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("license") != "CC0 1.0 Universal":
        raise RuntimeError("Unexpected asset license")
    build_lighting(stage, seed, assets_root)
    ground_material = build_terrain(stage, seed, assets_root)
    build_distant_terrain(stage, seed, ground_material)
    build_river(stage, seed, assets_root)
    nature_counts = scatter_nature(stage, seed, assets_root)
    build_landmarks(stage, seed, assets_root)
    return {
        "environment_version": "mountain-valley-v2",
        "environment_revision": "horizon-fix-v3-launch-pad",
        "asset_source": "Poly Haven",
        "asset_license": "CC0 1.0 Universal",
        "asset_count": len(manifest["assets"]),
        "terrain_grid": [161, 161],
        "distant_terrain_grid": [161, 161],
        "terrain_extent_m": 650.0,
        "distant_terrain_extent_m": 2400.0,
        "launch_clearing_radius_m": {
            "trees": 80.0,
            "mature_trees": 90.0,
            "groundcover": 60.0,
            "rocks": 40.0,
            "debris": 60.0,
        },
        **nature_counts,
    }


def orbit(center, radius, altitude, label, count=8, clockwise=False):
    points = []
    direction = -1.0 if clockwise else 1.0
    for i in range(count):
        theta = direction * 2.0 * math.pi * i / count
        points.append((
            center[0] + radius * math.cos(theta),
            center[1] + radius * math.sin(theta), altitude, label,
        ))
    return points


def finish_route(label="return to the launch clearing"):
    return [(28.0, -8.0, 18.0, label), (0.0, 0.0, 9.0, "align over the launch pad"),
            (0.0, 0.0, 0.15, "descend and land")]


def mission_definition(episode_id, seed):
    missions = []
    missions.append({
        "mission_id": "upper-river-waterfall-recon",
        "task_type": "river reconnaissance",
        "instruction": "Take off from the valley clearing, follow the river upstream beneath the timber footbridge, inspect the confluence, orbit the upper waterfall once, then return along the south bank and land at the launch pad.",
        "landmarks": ["timber footbridge", "stream confluence", "upper waterfall"],
        "waypoints": [(0, 0, 18, "take off above the valley clearing"), (38, river_y(38), 20, "follow the river upstream"), (72, river_y(72), 22, "pass beneath the timber footbridge corridor"), (145, 8, 25, "inspect the stream confluence"), (215, river_y(215), 28, "continue toward the upper waterfall")] + orbit((260, river_y(260)), 15, 31, "orbit the upper waterfall") + [(170, -18, 25, "return along the south bank"), (85, -14, 21, "follow the lower river home")] + finish_route(),
    })
    missions.append({
        "mission_id": "western-forest-deadwood-survey",
        "task_type": "forest survey",
        "instruction": "Climb from the launch clearing, survey the western conifer edge in a shallow S-pattern, circle the fallen deadwood site, cross the fern meadow, and return to land from the northwest.",
        "landmarks": ["western conifer edge", "fallen deadwood", "fern meadow"],
        "waypoints": [(0, 0, 19, "take off above the launch clearing"), (-42, 28, 24, "enter the western conifer edge"), (-88, 54, 28, "survey the north forest transect"), (-132, 18, 27, "cross to the western forest pocket")] + orbit((-150, -22), 14, 27, "circle the fallen deadwood site", clockwise=True) + [(-110, -58, 25, "cross the fern meadow"), (-58, -38, 22, "return from the northwest")] + finish_route("approach the launch clearing"),
    })
    missions.append({
        "mission_id": "stone-cairn-photogrammetry-orbit",
        "task_type": "landmark imaging",
        "instruction": "Fly southeast along the alternate river bank, climb to the stone cairn, perform two imaging arcs at different radii, exit through the confluence, and return to the starting pad.",
        "landmarks": ["alternate river bank", "stone cairn", "stream confluence"],
        "waypoints": [(0, 0, 18, "take off"), (52, -18, 21, "follow the alternate river bank"), (105, -32, 25, "climb toward the cairn"), (145, -45, 28, "approach the stone cairn")] + orbit((180, -55), 18, 31, "capture the wide cairn orbit") + orbit((180, -55), 10, 25, "capture the close cairn orbit", clockwise=True) + [(145, 8, 25, "exit through the stream confluence"), (75, 10, 21, "follow the river home")] + finish_route(),
    })
    missions.append({
        "mission_id": "footbridge-structural-inspection",
        "task_type": "infrastructure inspection",
        "instruction": "Approach the timber footbridge from downstream, inspect its upstream and downstream faces, make a complete clockwise orbit above the bridge, then follow the river back and land.",
        "landmarks": ["timber footbridge"],
        "waypoints": [(0, 0, 17, "take off"), (30, river_y(30), 18, "approach the bridge from downstream"), (60, river_y(60) - 10, 20, "inspect the downstream face"), (72, river_y(72) + 11, 20, "inspect the upstream face")] + orbit((72, river_y(72)), 13, 24, "orbit the timber footbridge", clockwise=True) + [(40, river_y(40), 19, "follow the river downstream")] + finish_route(),
    })
    missions.append({
        "mission_id": "north-slope-rockslide-assessment",
        "task_type": "hazard assessment",
        "instruction": "Ascend the north slope toward the recent rockslide, scan the debris field from west to east, orbit the largest boulder, descend through the saddle, and land at the valley clearing.",
        "landmarks": ["north slope", "rockslide debris field", "largest boulder", "saddle"],
        "waypoints": [(0, 0, 20, "take off and begin the north-slope climb"), (65, 35, 27, "climb above the north slope"), (130, 58, 32, "approach the rockslide from the west"), (195, 68, 35, "scan the western debris field"), (220, 78, 36, "scan the central debris field"), (242, 70, 36, "scan the eastern debris field")] + orbit((220, 75), 15, 38, "orbit the largest slide boulder") + [(190, 46, 31, "descend through the saddle"), (100, 22, 24, "return to the valley floor")] + finish_route(),
    })
    missions.append({
        "mission_id": "south-meadow-search-grid",
        "task_type": "area search",
        "instruction": "Fly to the south meadow and execute a four-lane visual search grid from west to east, check the orange survey marker, then return directly to the launch pad and land.",
        "landmarks": ["south meadow", "orange survey marker"],
        "waypoints": [(0, 0, 20, "take off"), (-35, -42, 24, "enter the south meadow"), (-95, -72, 27, "start search lane one"), (-25, -72, 27, "complete search lane one"), (-25, -92, 27, "shift to lane two"), (-105, -92, 27, "complete search lane two"), (-105, -112, 28, "shift to lane three"), (-20, -112, 28, "complete search lane three"), (-20, -132, 30, "shift to lane four"), (-110, -132, 30, "complete search lane four"), (-55, -95, 25, "check the orange survey marker")] + finish_route("return directly to the launch clearing"),
    })
    missions.append({
        "mission_id": "fire-lookout-perimeter-check",
        "task_type": "lookout inspection",
        "instruction": "Climb along the north forest boundary to the fire lookout, circle the tower counterclockwise while keeping the cabin in view, inspect the beacon, and descend by the river corridor to land.",
        "landmarks": ["north forest boundary", "fire lookout tower", "lookout beacon"],
        "waypoints": [(0, 0, 20, "take off"), (45, 32, 27, "climb along the north forest boundary"), (88, 60, 32, "approach the fire lookout"), (112, 77, 37, "align for the tower orbit")] + orbit((130, 85), 17, 40, "orbit the fire lookout tower") + [(130, 85, 45, "inspect the lookout beacon"), (95, 38, 31, "descend toward the river corridor"), (55, river_y(55), 23, "follow the river corridor home")] + finish_route(),
    })
    missions.append({
        "mission_id": "confluence-branch-mapping",
        "task_type": "stream mapping",
        "instruction": "Map the stream confluence by tracing the main channel, flying the north branch to its bend, crossing to the south branch, and closing the loop around the confluence before returning to land.",
        "landmarks": ["main river channel", "north stream branch", "south stream branch", "stream confluence"],
        "waypoints": [(0, 0, 18, "take off"), (55, river_y(55), 21, "trace the main river channel"), (105, river_y(105), 23, "continue to the confluence"), (145, 8, 25, "mark the stream confluence"), (170, 35, 27, "trace the north stream branch"), (195, 54, 30, "reach the north branch bend"), (175, 5, 28, "cross between stream branches"), (165, -32, 27, "trace the south stream branch"), (135, -20, 25, "close the confluence loop"), (90, river_y(90), 22, "return along the main channel")] + finish_route(),
    })
    missions.append({
        "mission_id": "southern-cliff-gate-transit",
        "task_type": "terrain transit",
        "instruction": "Follow the river to the upper valley, turn south through the paired cliff gate, cross the high saddle, photograph the rock faces from both sides, and return below the north ridge to land.",
        "landmarks": ["upper valley", "paired cliff gate", "high saddle", "north ridge"],
        "waypoints": [(0, 0, 20, "take off"), (65, river_y(65), 23, "follow the river into the upper valley"), (135, river_y(135), 27, "continue through the upper valley"), (210, -22, 33, "turn south toward the cliff gate"), (275, -62, 42, "transit the paired cliff gate"), (305, -38, 47, "cross the high saddle"), (285, -72, 45, "photograph the southern rock face"), (255, -44, 40, "photograph the northern rock face"), (205, 12, 34, "return below the north ridge"), (110, 12, 26, "descend toward the launch valley")] + finish_route(),
    })
    missions.append({
        "mission_id": "multi-landmark-valley-patrol",
        "task_type": "long-range patrol",
        "instruction": "Complete a full valley patrol: pass the timber bridge, orbit the stone cairn, climb around the fire lookout, inspect the waterfall, return through the cliff-gate approach, and land at the starting clearing.",
        "landmarks": ["timber footbridge", "stone cairn", "fire lookout", "upper waterfall", "cliff gate"],
        "waypoints": [(0, 0, 21, "take off for the valley patrol"), (72, river_y(72), 24, "pass the timber footbridge"), (130, -28, 28, "turn toward the stone cairn")] + orbit((180, -55), 15, 32, "orbit the stone cairn", count=6) + [(165, 30, 34, "climb toward the fire lookout")] + orbit((130, 85), 18, 41, "circle the fire lookout", count=6) + [(185, 35, 35, "cross toward the upper river"), (260, river_y(260), 34, "inspect the upper waterfall"), (275, -52, 42, "pass the cliff-gate approach"), (190, -28, 32, "begin the homeward river leg"), (95, river_y(95), 25, "follow the river home")] + finish_route(),
    })
    mission = missions[episode_id % len(missions)]
    mission = dict(mission)
    mission["episode_id"] = episode_id
    mission["seed"] = seed
    mission["waypoints_enu_m"] = mission.pop("waypoints")
    mission["landing_index"] = len(mission["waypoints_enu_m"]) - 1
    mission["max_sim_seconds"] = 440.0
    return mission
