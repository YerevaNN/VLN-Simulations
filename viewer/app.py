import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from flask import Flask, abort, jsonify, send_from_directory


DATASET_ROOT = Path(os.environ.get("UAV_DATASET_ROOT", "/data")).resolve()
DATASET_NAME = os.environ.get("UAV_DATASET_NAME", DATASET_ROOT.name)
EPISODE_RE = re.compile(r"episode-\d{3}")

app = Flask(__name__, static_folder="static", static_url_path="")


def episode_path(name: str) -> Path:
    if not EPISODE_RE.fullmatch(name):
        abort(404)
    path = (DATASET_ROOT / name).resolve()
    if path.parent != DATASET_ROOT or not path.is_dir():
        abort(404)
    return path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def records(path: Path):
    return pq.read_table(path).to_pylist()


def river_y(x):
    return 7.0 * math.sin(x / 70.0) + 3.0 * math.sin(x / 31.0)


def safe_from_landmarks(x, y):
    landmarks = ((0, 0), (72, river_y(72)), (145, 8), (180, -55), (130, 85), (260, river_y(260)))
    return all(math.hypot(x - lx, y - ly) > 12.0 for lx, ly in landmarks)


def clear_of_launch(x, y, radius):
    return math.hypot(x, y) >= radius


@lru_cache(maxsize=1)
def route_segments():
    segments = []
    for path in sorted(DATASET_ROOT.glob("episode-*/mission.json")):
        route = read_json(path).get("waypoints_enu_m", [])
        segments.extend(zip(route, route[1:]))
    return segments


def clear_of_routes(x, y, clearance):
    for start, end in route_segments():
        ax, ay = start[:2]
        bx, by = end[:2]
        dx, dy = bx - ax, by - ay
        denominator = max(dx * dx + dy * dy, 1e-6)
        fraction = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / denominator))
        if math.hypot(x - (ax + fraction * dx), y - (ay + fraction * dy)) < clearance:
            return False
    return True


@lru_cache(maxsize=16)
def environment_map(seed):
    """Reproduce the exact deterministic XY scatter used by the Isaac scene."""
    rng = np.random.default_rng(seed)
    trees, groundcover, rocks, debris = [], [], [], []
    tree_types = ("fir", "pine")
    cover_types = ("grass", "fern", "shrub")
    rock_types = ("small-rock", "stone", "rock", "boulder")
    debris_types = ("stump", "dead-log")

    for _ in range(520):
        x = float(rng.uniform(-310, 390))
        side = float(rng.choice([-1, 1]))
        y = river_y(x) + side * float(rng.uniform(25, 205))
        if (not safe_from_landmarks(x, y) or not clear_of_launch(x, y, 80.0)
                or not clear_of_routes(x, y, 35.0)):
            continue
        prototype = int(rng.integers(0, 2))
        scale = float(rng.uniform(1.5, 3.0))
        rng.uniform(-math.pi, math.pi)
        trees.append([round(x, 2), round(y, 2), tree_types[prototype], round(scale, 2)])

    for _ in range(145):
        x = float(rng.uniform(-300, 390))
        y = river_y(x) + float(rng.choice([-1, 1])) * float(rng.uniform(48, 190))
        if (not safe_from_landmarks(x, y) or not clear_of_launch(x, y, 90.0)
                or not clear_of_routes(x, y, 45.0)):
            continue
        scale = float(rng.uniform(0.30, 0.50))
        rng.uniform(-math.pi, math.pi)
        trees.append([round(x, 2), round(y, 2), "mature-tree", round(scale, 2)])

    for _ in range(950):
        x = float(rng.uniform(-290, 370))
        y = river_y(x) + float(rng.choice([-1, 1])) * float(rng.uniform(10, 155))
        if not clear_of_launch(x, y, 60.0):
            continue
        prototype = int(rng.integers(0, 3))
        scale = float(rng.uniform((1.2, 0.7, 0.35)[prototype], (2.8, 1.8, 0.95)[prototype]))
        rng.uniform(-math.pi, math.pi)
        groundcover.append([round(x, 2), round(y, 2), cover_types[prototype], round(scale, 2)])

    for _ in range(380):
        x = float(rng.uniform(-280, 380))
        y = river_y(x) + float(rng.choice([-1, 1])) * float(rng.uniform(4.5, 28.0))
        if not clear_of_launch(x, y, 40.0):
            continue
        prototype = int(rng.integers(0, 4))
        scale = float(rng.uniform(0.45, 2.2))
        rng.uniform(-math.pi, math.pi)
        rocks.append([round(x, 2), round(y, 2), rock_types[prototype], round(scale, 2)])

    for _ in range(55):
        x = float(rng.uniform(-230, 340))
        y = river_y(x) + float(rng.choice([-1, 1])) * float(rng.uniform(18, 120))
        if not clear_of_launch(x, y, 60.0):
            continue
        prototype = int(rng.integers(0, 2))
        scale = float(rng.uniform(0.7, 1.4))
        rng.uniform(-math.pi, math.pi)
        debris.append([round(x, 2), round(y, 2), debris_types[prototype], round(scale, 2)])

    for _ in range(1200):
        x = float(rng.uniform(-1200, 1600))
        y = river_y(x) + float(rng.choice([-1, 1])) * float(rng.uniform(300, 850))
        prototype = int(rng.integers(0, 2))
        scale = float(rng.uniform(1.5, 3.4))
        rng.uniform(-math.pi, math.pi)
        trees.append([round(x, 2), round(y, 2), tree_types[prototype], round(scale, 2)])

    slide_rng = np.random.default_rng(seed + 991)
    rockslide = []
    for _ in range(34):
        x = float(slide_rng.uniform(195, 242))
        y = float(slide_rng.uniform(58, 92))
        scale = float(slide_rng.uniform(1.8, 5.0))
        prototype = int(slide_rng.integers(0, 2))
        slide_rng.uniform(-math.pi, math.pi)
        rockslide.append([round(x, 2), round(y, 2), ("rock", "boulder")[prototype], round(scale, 2)])

    cliffs = []
    for index in range(18):
        x = 125.0 + index * 25.0
        side = -1.0 if index % 2 else 1.0
        y = river_y(x) + side * (150.0 + 18.0 * math.sin(index * 1.7))
        cliffs.append([round(x, 2), round(y, 2), "valley-wall"])
    cliffs.extend([[285.0, -70.0, "cliff-gate"], [294.0, -57.0, "cliff-gate"]])

    landmarks = [
        [0.0, 0.0, "Launch"],
        [72.0, round(river_y(72.0), 2), "Bridge"],
        [145.0, 8.0, "Confluence"],
        [180.0, -55.0, "Cairn"],
        [130.0, 85.0, "Lookout"],
        [260.0, round(river_y(260.0), 2), "Waterfall"],
        [220.0, 75.0, "Rockslide"],
        [289.5, -63.5, "Cliff gate"],
    ]
    river = [[round(float(x), 2), round(river_y(float(x)), 2)] for x in np.linspace(-1200.0, 1600.0, 281)]
    return {
        "river": river,
        "trees": trees,
        "groundcover": groundcover,
        "rocks": rocks,
        "debris": debris,
        "rockslide": rockslide,
        "cliffs": cliffs,
        "landmarks": landmarks,
    }


def public_manifest(manifest):
    keys = (
        "episode_id", "status", "seed", "duration_s", "path_length_m",
        "frame_count", "action_count", "state_count", "camera", "action_hz",
        "simulator", "autopilot", "vehicle_target", "simulation_vehicle",
        "controller_interface",
    )
    return {key: manifest.get(key) for key in keys if key in manifest}


@lru_cache(maxsize=16)
def build_timeline(name: str):
    root = episode_path(name)
    mission = read_json(root / "mission.json")
    manifest = read_json(root / "manifest.json")
    frames = records(root / "frames.parquet")
    actions = records(root / "joystick.parquet")
    states = records(root / "vehicle_state.parquet")
    events = records(root / "events.parquet")

    return {
        "episode": name,
        "manifest": public_manifest(manifest),
        "mission": mission,
        "environment_map": environment_map(int(mission["seed"])),
        "frames": [
            [row["sim_time_s"], f"/data/{name}/{Path(row['path']).name}"]
            for row in frames
        ],
        "actions": [
            [row["sim_time_s"], row["roll"], row["pitch"], row["yaw"],
             row["throttle"], row["waypoint_index"], row["subgoal"]]
            for row in actions
        ],
        "states": [
            [row["sim_time_s"], row["x_enu_m"], row["y_enu_m"], row["z_enu_m"],
             row["vx_enu_mps"], row["vy_enu_mps"], row["vz_enu_mps"],
             row["roll_rad"], row["pitch_rad"], row["yaw_rad"],
             bool(row["armed"]), row["waypoint_index"]]
            for row in states
        ],
        "events": [[row["sim_time_s"], row["type"], row["payload"]] for row in events],
    }


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/health")
def health():
    episodes = sorted(path.name for path in DATASET_ROOT.glob("episode-*") if path.is_dir())
    return jsonify({"status": "ok", "dataset": DATASET_NAME, "episodes": len(episodes)})


@app.get("/api/episodes")
def episodes():
    result = []
    for path in sorted(DATASET_ROOT.glob("episode-*")):
        if not path.is_dir() or not EPISODE_RE.fullmatch(path.name):
            continue
        mission = read_json(path / "mission.json")
        manifest = read_json(path / "manifest.json")
        result.append({
            "id": path.name,
            "instruction": mission.get("instruction"),
            "mission_id": mission.get("mission_id"),
            "manifest": public_manifest(manifest),
        })
    return jsonify(result)


@app.get("/api/episodes/<name>")
def timeline(name):
    return jsonify(build_timeline(name))


@app.get("/data/<name>/<filename>")
def frame(name, filename):
    root = episode_path(name) / "frames"
    if Path(filename).name != filename or not filename.lower().endswith((".jpg", ".jpeg")):
        abort(404)
    response = send_from_directory(root, filename, conditional=True)
    response.headers["Cache-Control"] = "public, max-age=86400, immutable"
    return response


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8787")))
