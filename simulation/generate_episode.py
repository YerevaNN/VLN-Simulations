#!/usr/bin/env python3
"""Generate one fully automatic PX4/Pegasus UAV dataset episode in Isaac Sim.

Run this file with Isaac Sim's Python interpreter. The surrounding launcher mounts
the repository at /workspace and bulk output at /data.
"""

from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": True, "width": 640, "height": 360})

import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import time
from pathlib import Path

import numpy as np
import omni.timeline
import pandas as pd
from omni.isaac.core.world import World
from PIL import Image
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdPhysics
from pymavlink import mavutil
from scipy.spatial.transform import Rotation

import pegasus.simulator.logic.backends.px4_mavlink_backend as px4_backend_module
from pegasus.simulator.logic.backends.px4_mavlink_backend import (
    PX4MavlinkBackend,
    PX4MavlinkBackendConfig,
)
from pegasus.simulator.logic.backends.tools.px4_launch_tool import PX4LaunchTool
from pegasus.simulator.logic.graphical_sensors.monocular_camera import MonocularCamera
from pegasus.simulator.logic.interface.pegasus_interface import PegasusInterface
from pegasus.simulator.logic.vehicles.multirotor import Multirotor, MultirotorConfig
from pegasus.simulator.params import ROBOTS


CAMERA_HZ = 10.0
CAMERA_SENSOR_HZ = 20.0
ACTION_HZ = 50.0
STATE_HZ = 50.0
MAX_SIM_SECONDS = 260.0
IMAGE_SIZE = (640, 360)
CAMERA_NEAR_CLIP_M = 0.05
CAMERA_FAR_CLIP_M = 5000.0
CAMERA_MOUNT_XYZ_M = (0.30, 0.0, 0.35)
CAMERA_MOUNT_RPY_DEG = (0.0, -3.0, 180.0)


class LongRangeMonocularCamera(MonocularCamera):
    """Pegasus camera with an explicit far plane suitable for outdoor flight.

    Pegasus Simulator 5.1 hard-codes its camera far plane to 100 m in
    ``MonocularCamera.start``.  Overriding it after initialization prevents
    terrain and landmarks from being clipped as the UAV approaches them.
    """

    def start(self):
        super().start()
        self._camera.set_clipping_range(CAMERA_NEAR_CLIP_M, CAMERA_FAR_CLIP_M)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode-id", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-root", default="/data/datasets/poc-v1")
    parser.add_argument("--px4-dir", default="/workspace/PX4-Autopilot")
    parser.add_argument("--scene-version", choices=("v1", "v2"), default="v1")
    parser.add_argument("--assets-root", default="/assets")
    return parser.parse_args()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def terrain_height(x, y, seed):
    """Deterministic broad valley with higher ridges away from the route."""
    if x * x + y * y < 85.0**2:
        return 0.0
    valley_centre = 24.0 * math.sin(x / 260.0)
    lateral = min(abs(y - valley_centre), 1000.0)
    ridge = 260.0 * (lateral / 1000.0) ** 1.18
    undulation = 7.0 * math.sin(x / 190.0 + seed * 0.11) * (abs(y) / 1000.0)
    side_valley = -18.0 * math.exp(-((y + 260.0 - 0.18 * x) / 150.0) ** 2)
    return max(-3.0, ridge + undulation + side_valley)


def set_color(prim, rgb):
    UsdGeom.Gprim(prim).CreateDisplayColorAttr().Set([Gf.Vec3f(*rgb)])


def build_environment(stage, seed):
    rng = np.random.default_rng(seed)
    grid_n = 97
    extent = 2000.0
    coords = np.linspace(-extent, extent, grid_n)
    points = []
    colors = []
    for y in coords:
        for x in coords:
            z = terrain_height(float(x), float(y), seed)
            points.append(Gf.Vec3f(float(x), float(y), float(z)))
            green = np.clip(0.29 + z / 700.0 + rng.normal(0, 0.015), 0.24, 0.48)
            colors.append(Gf.Vec3f(float(green * 0.72), float(green), float(green * 0.52)))

    indices = []
    counts = []
    for row in range(grid_n - 1):
        for col in range(grid_n - 1):
            a = row * grid_n + col
            b = a + 1
            c = a + grid_n
            d = c + 1
            indices.extend([a, b, d, a, d, c])
            counts.extend([3, 3])

    mesh = UsdGeom.Mesh.Define(stage, "/World/Terrain")
    mesh.CreatePointsAttr(points)
    mesh.CreateFaceVertexIndicesAttr(indices)
    mesh.CreateFaceVertexCountsAttr(counts)
    mesh.CreateSubdivisionSchemeAttr().Set("none")
    mesh.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex).Set(colors)
    mesh.CreateExtentAttr(UsdGeom.Mesh.ComputeExtent(points))
    UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())

    light = UsdLux.DistantLight.Define(stage, "/World/Sun")
    light.CreateIntensityAttr(1800.0 + 250.0 * (seed % 3))
    light.CreateAngleAttr(0.7)
    light.CreateColorAttr(Gf.Vec3f(1.0, 0.94 + 0.02 * (seed % 3), 0.84))
    UsdGeom.Xformable(light).AddRotateXYZOp().Set(Gf.Vec3f(35.0, -25.0, 25.0 + 20 * (seed % 3)))

    sky = UsdLux.DomeLight.Define(stage, "/World/Sky")
    sky.CreateIntensityAttr(450.0)
    sky.CreateColorAttr(Gf.Vec3f(0.52, 0.68, 0.92))

    # A flat blue river ribbon follows the mission's main valley.
    river_points = []
    river_faces = []
    river_samples = np.linspace(-250, 350, 49)
    for x in river_samples:
        y = 8.0 * math.sin(x / 75.0)
        z = terrain_height(x, y, seed) + 0.12
        river_points.extend(
            [Gf.Vec3f(float(x), float(y - 1.8), z), Gf.Vec3f(float(x), float(y + 1.8), z)]
        )
    for i in range(len(river_samples) - 1):
        a = 2 * i
        river_faces.extend([a, a + 1, a + 3, a, a + 3, a + 2])
    river = UsdGeom.Mesh.Define(stage, "/World/River")
    river.CreatePointsAttr(river_points)
    river.CreateFaceVertexIndicesAttr(river_faces)
    river.CreateFaceVertexCountsAttr([3] * (len(river_faces) // 3))
    river.CreateSubdivisionSchemeAttr().Set("none")
    set_color(river.GetPrim(), (0.035, 0.24, 0.36))

    # Sparse procedural conifers and rocks, kept outside the flight corridor.
    for i in range(220):
        x = float(rng.uniform(-350, 500))
        y = float(rng.choice([-1, 1]) * rng.uniform(20, 300))
        z = terrain_height(x, y, seed)
        height = float(rng.uniform(5.0, 11.0))
        trunk = UsdGeom.Cylinder.Define(stage, f"/World/Vegetation/Tree_{i:03d}/Trunk")
        trunk.CreateRadiusAttr(0.35)
        trunk.CreateHeightAttr(height * 0.45)
        trunk.AddTranslateOp().Set(Gf.Vec3d(x, y, z + height * 0.225))
        set_color(trunk.GetPrim(), (0.20, 0.11, 0.05))
        crown = UsdGeom.Cone.Define(stage, f"/World/Vegetation/Tree_{i:03d}/Crown")
        crown.CreateRadiusAttr(height * 0.22)
        crown.CreateHeightAttr(height)
        crown.AddTranslateOp().Set(Gf.Vec3d(x, y, z + height * 0.72))
        set_color(crown.GetPrim(), (0.06, 0.23 + 0.03 * (i % 3), 0.09))

    for i in range(45):
        x = float(rng.uniform(-500, 500))
        y = float(rng.choice([-1, 1]) * rng.uniform(65, 260))
        z = terrain_height(x, y, seed)
        rock = UsdGeom.Sphere.Define(stage, f"/World/Rocks/Rock_{i:03d}")
        scale = float(rng.uniform(0.8, 3.0))
        rock.CreateRadiusAttr(1.0)
        rock.AddTranslateOp().Set(Gf.Vec3d(x, y, z + scale * 0.5))
        rock.AddScaleOp().Set(Gf.Vec3f(scale, scale * 0.75, scale * 0.55))
        set_color(rock.GetPrim(), (0.31, 0.29, 0.25))

    # Distinctive remote-valley landmark used by the language mission.
    cairn_x, cairn_y = 116.0, -19.0
    for i, radius in enumerate([3.4, 2.6, 1.8, 1.0]):
        cairn = UsdGeom.Cylinder.Define(stage, f"/World/Landmarks/Cairn_{i}")
        cairn.CreateRadiusAttr(radius)
        cairn.CreateHeightAttr(1.5)
        cairn.AddTranslateOp().Set(
            Gf.Vec3d(cairn_x, cairn_y, terrain_height(cairn_x, cairn_y, seed) + 0.75 + i * 1.5)
        )
        set_color(cairn.GetPrim(), (0.55, 0.49, 0.40))


class FixedPX4LaunchTool(PX4LaunchTool):
    """Work around Pegasus 5.1 launching PX4 with an empty root filesystem."""

    def launch_px4(self):
        source = Path(self.px4_dir) / "build" / "px4_sitl_default" / "etc"
        shutil.copytree(source, Path(self.root_fs.name) / "etc", dirs_exist_ok=True)
        super().launch_px4()


class HumanLikeExpert:
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)
        self.command = np.zeros(4, dtype=float)  # roll, pitch, yaw, throttle
        self.noise = np.zeros(4, dtype=float)

    @staticmethod
    def clamp(value, low, high):
        return max(low, min(high, value))

    def step(self, state, target, dt, allow_horizontal=True):
        position = state.position
        delta = np.asarray(target, dtype=float) - position
        rotation = Rotation.from_quat(state.attitude)
        body_delta = rotation.inv().apply(delta)
        heading_error = math.atan2(body_delta[1], max(0.01, body_delta[0]))

        pitch = self.clamp(0.055 * body_delta[0], -0.82, 0.82)
        roll = self.clamp(-0.050 * body_delta[1], -0.62, 0.62)
        yaw = self.clamp(-0.90 * heading_error, -0.55, 0.55)
        throttle = self.clamp(0.16 * delta[2] - 0.12 * state.linear_velocity[2], -0.85, 1.0)
        if abs(body_delta[0]) > 5.0 and abs(pitch) < 0.24:
            pitch = math.copysign(0.24, body_delta[0])
        if abs(body_delta[1]) > 4.0 and abs(roll) < 0.18:
            roll = -math.copysign(0.18, body_delta[1])
        if not allow_horizontal:
            roll = pitch = yaw = 0.0
        if abs(heading_error) > 0.75:
            pitch *= 0.25

        desired = np.array([roll, pitch, yaw, throttle])
        # Correlated, low-amplitude stick wander plus reaction smoothing and rate limits.
        self.noise = 0.94 * self.noise + self.rng.normal(0.0, [0.004, 0.004, 0.003, 0.002])
        desired += self.noise
        desired[np.abs(desired) < 0.012] = 0.0
        filtered = self.command + 0.18 * (desired - self.command)
        max_delta = np.array([0.035, 0.035, 0.025, 0.045]) * max(dt * ACTION_HZ, 0.5)
        self.command += np.clip(filtered - self.command, -max_delta, max_delta)
        self.command = np.clip(self.command, -1.0, 1.0)
        return self.command.copy()


def mission_definition(seed):
    outbound = [
        (0.0, 0.0, 16.0, "take off above valley base"),
        (25.0, 2.0, 18.0, "follow the river"),
        (55.0, 10.0, 22.0, "pass the split boulder"),
        (80.0, -2.0, 25.0, "enter the side valley"),
        (105.0, -16.0, 29.0, "cross the saddle"),
    ]
    centre = np.array([116.0, -19.0, 29.0])
    orbit = []
    for i in range(8):
        theta = 2.0 * math.pi * i / 8.0
        point = centre + np.array([12.0 * math.cos(theta), 12.0 * math.sin(theta), 0.0])
        orbit.append((*point.tolist(), "orbit the stone cairn"))
    returning = [
        (85.0, -30.0, 25.0, "return through the alternate branch"),
        (52.0, -23.0, 22.0, "follow the west river branch"),
        (22.0, -10.0, 18.0, "approach the valley base"),
        (0.0, 0.0, 10.0, "align over the landing area"),
        (0.0, 0.0, 0.15, "descend and land"),
    ]
    return {
        "mission_id": "valley-cairn-return-v1",
        "instruction": (
            "Take off from the valley base, follow the river past the split boulder, "
            "cross the side-valley saddle, orbit the stone cairn once, return through "
            "the alternate river branch, and land at the starting pad."
        ),
        "seed": seed,
        "waypoints_enu_m": outbound + orbit + returning,
        "orbit_start_index": len(outbound),
        "landing_index": len(outbound) + len(orbit) + len(returning) - 1,
    }


def manual_send(gcs, target_system, command):
    roll, pitch, yaw, throttle = command
    gcs.mav.manual_control_send(
        target_system,
        int(np.clip(pitch, -1, 1) * 1000),
        int(np.clip(roll, -1, 1) * 1000),
        int(np.clip((throttle + 1.0) * 500, 0, 1000)),
        int(np.clip(yaw, -1, 1) * 1000),
        0,
    )


def request_mode(gcs, target_system):
    gcs.mav.set_mode_send(
        target_system,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        3 << 16,  # PX4_CUSTOM_MAIN_MODE_POSCTL
    )


def request_arm(gcs, target_system, arm):
    gcs.mav.command_long_send(
        target_system,
        1,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        1 if arm else 0,
        0 if arm else 21196,
        0,
        0,
        0,
        0,
        0,
    )


def export_training_views(episode_dir, frames, actions, mission):
    action_times = np.asarray([row["sim_time_s"] for row in actions])
    for rate in (2, 5, 10):
        output = episode_dir / "exports" / f"{rate}hz.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        min_spacing = 1.0 / rate
        last = -1e9
        with output.open("w", encoding="utf-8") as stream:
            for frame in frames:
                if frame["sim_time_s"] - last < min_spacing - 0.002:
                    continue
                idx = int(np.argmin(np.abs(action_times - frame["sim_time_s"])))
                row = {
                    "episode_id": episode_dir.name,
                    "timestamp_s": frame["sim_time_s"],
                    "image": frame["path"],
                    "mission": mission["instruction"],
                    "subgoal": actions[idx]["subgoal"],
                    "action": {key: actions[idx][key] for key in ("roll", "pitch", "yaw", "throttle")},
                }
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                last = frame["sim_time_s"]


def main():
    args = parse_args()
    episode_dir = Path(args.output_root) / f"episode-{args.episode_id:03d}"
    if episode_dir.exists():
        shutil.rmtree(episode_dir)
    frames_dir = episode_dir / "frames"
    frames_dir.mkdir(parents=True)
    if args.scene_version == "v2":
        from natural_valley import (
            build_environment as build_environment_v2,
            mission_definition as mission_definition_v2,
        )

        mission = mission_definition_v2(args.episode_id, args.seed)
    else:
        mission = mission_definition(args.seed)
    write_json(episode_dir / "mission.json", mission)

    px4_backend_module.PX4LaunchTool = FixedPX4LaunchTool
    timeline = omni.timeline.get_timeline_interface()
    pg = PegasusInterface()
    pg._world = World(**pg._world_settings)
    world = pg.world
    if args.scene_version == "v2":
        environment_metadata = build_environment_v2(world.stage, args.seed, args.assets_root)
    else:
        build_environment(world.stage, args.seed)
        environment_metadata = {"environment_version": "procedural-valley-v1"}

    backend = PX4MavlinkBackend(
        PX4MavlinkBackendConfig(
            {
                "vehicle_id": 0,
                "px4_autolaunch": True,
                "px4_dir": args.px4_dir,
                "px4_vehicle_model": "gazebo-classic_iris",
                "enable_lockstep": True,
            }
        )
    )
    camera = LongRangeMonocularCamera(
        "forward_camera",
        config={
            "frequency": CAMERA_SENSOR_HZ,
            "resolution": IMAGE_SIZE,
            "depth": False,
            # The Iris proxy settles with its articulation origin slightly
            # below the terrain.  Keep the optical centre above ground during
            # takeoff and touchdown while approximating an X500 front mount.
            "position": np.array(CAMERA_MOUNT_XYZ_M),
            "orientation": np.array(CAMERA_MOUNT_RPY_DEG),
            "diagonal_fov": 98.0,
            "intrinsics": np.array([[380.0, 0.0, 320.0], [0.0, 380.0, 180.0], [0.0, 0.0, 1.0]]),
            "distortion_coefficients": [0.0] * 8,
        },
    )
    config = MultirotorConfig()
    config.backends = [backend]
    config.graphical_sensors = [camera]
    vehicle = Multirotor(
        "/World/X500v2",
        ROBOTS["Iris"],
        0,
        [0.0, 0.0, 0.12],
        Rotation.identity().as_quat(),
        config=config,
    )

    world.reset()
    timeline.play()
    gcs = mavutil.mavlink_connection(
        "udpin:0.0.0.0:14550", source_system=255, source_component=190
    )
    tlog_stream = (episode_dir / "mavlink.tlog").open("wb")

    expert = HumanLikeExpert(args.seed + 1000)
    actions = []
    states = []
    frames = []
    events = []
    heartbeat = None
    armed = False
    finished = False
    waypoint_index = 0
    next_action_time = 0.0
    next_state_time = 0.0
    next_frame_time = 0.0
    last_mode_request = -1e9
    last_arm_request = -1e9
    last_disarm_request = -1e9
    landing_started = None
    wall_start = time.time()
    waypoints = mission["waypoints_enu_m"]

    max_sim_seconds = float(mission.get("max_sim_seconds", MAX_SIM_SECONDS))
    while simulation_app.is_running() and world.current_time < max_sim_seconds:
        next_frame_due = world.current_time >= next_frame_time - 0.001
        world.step(render=next_frame_due)
        sim_time = float(world.current_time)

        while True:
            msg = gcs.recv_match(blocking=False)
            if msg is None:
                break
            tlog_stream.write(struct.pack(">Q", int(time.time() * 1_000_000)) + msg.get_msgbuf())
            if (
                msg.get_type() == "HEARTBEAT"
                and msg.autopilot != mavutil.mavlink.MAV_AUTOPILOT_INVALID
            ):
                heartbeat = msg
                armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            elif msg.get_type() in ("COMMAND_ACK", "STATUSTEXT"):
                events.append({"sim_time_s": sim_time, "type": msg.get_type(), "payload": json.dumps(msg.to_dict())})

        if heartbeat is not None:
            target_system = heartbeat.get_srcSystem()
            if sim_time - last_mode_request >= 1.0 and not armed and landing_started is None:
                request_mode(gcs, target_system)
                last_mode_request = sim_time
            if (
                sim_time > 6.0
                and sim_time - last_arm_request >= 1.0
                and not armed
                and landing_started is None
            ):
                request_arm(gcs, target_system, True)
                last_arm_request = sim_time

            if sim_time >= next_action_time - 0.001:
                target = waypoints[waypoint_index]
                allow_horizontal = armed and sim_time > 7.0
                command = expert.step(vehicle.state, target[:3], 1.0 / ACTION_HZ, allow_horizontal)
                if not armed:
                    command[:] = 0.0
                manual_send(gcs, target_system, command)
                subgoal = target[3]
                actions.append(
                    {
                        "sim_time_s": sim_time,
                        "roll": float(command[0]),
                        "pitch": float(command[1]),
                        "yaw": float(command[2]),
                        "throttle": float(command[3]),
                        "buttons": 0,
                        "mode": "POSCTL",
                        "waypoint_index": waypoint_index,
                        "subgoal": subgoal,
                    }
                )
                while next_action_time <= sim_time + 0.001:
                    next_action_time += 1.0 / ACTION_HZ

                horizontal_distance = float(np.linalg.norm(vehicle.state.position[:2] - np.asarray(target[:2])))
                vertical_distance = abs(float(vehicle.state.position[2] - target[2]))
                is_landing = waypoint_index == mission["landing_index"]
                reached = (
                    horizontal_distance < (6.0 if not is_landing else 0.45)
                    and vertical_distance < (3.0 if not is_landing else 0.30)
                )
                if (
                    is_landing
                    and horizontal_distance < 2.5
                    and vehicle.state.position[2] < 0.9
                    and abs(vehicle.state.linear_velocity[2]) < 0.2
                ):
                    if landing_started is None:
                        landing_started = sim_time
                        events.append({"sim_time_s": sim_time, "type": "touchdown", "payload": "{}"})
                    if sim_time - landing_started > 1.0 and sim_time - last_disarm_request > 1.0:
                        request_arm(gcs, target_system, False)
                        last_disarm_request = sim_time
                if reached and not is_landing:
                    events.append(
                        {
                            "sim_time_s": sim_time,
                            "type": "waypoint_reached",
                            "payload": json.dumps({"index": waypoint_index, "subgoal": subgoal}),
                        }
                    )
                    waypoint_index += 1
                if landing_started is not None and not armed and sim_time - landing_started > 2.0:
                    finished = True

        if sim_time >= next_state_time - 0.001:
            state = vehicle.state
            roll, pitch, yaw = Rotation.from_quat(state.attitude).as_euler("XYZ")
            states.append(
                {
                    "sim_time_s": sim_time,
                    "x_enu_m": float(state.position[0]),
                    "y_enu_m": float(state.position[1]),
                    "z_enu_m": float(state.position[2]),
                    "vx_enu_mps": float(state.linear_velocity[0]),
                    "vy_enu_mps": float(state.linear_velocity[1]),
                    "vz_enu_mps": float(state.linear_velocity[2]),
                    "roll_rad": float(roll),
                    "pitch_rad": float(pitch),
                    "yaw_rad": float(yaw),
                    "armed": armed,
                    "waypoint_index": waypoint_index,
                }
            )
            while next_state_time <= sim_time + 0.001:
                next_state_time += 1.0 / STATE_HZ

        if next_frame_due and camera.state and camera.state.get("camera") is not None:
            rgba = camera.state["camera"].get_rgba()
            if rgba is not None and rgba.size:
                rgb = np.asarray(rgba[:, :, :3])
                if rgb.dtype != np.uint8:
                    rgb = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
                filename = f"rgb_{int(round(sim_time * 1_000_000)):012d}.jpg"
                Image.fromarray(rgb).save(frames_dir / filename, quality=90, subsampling=1)
                frames.append({"sim_time_s": sim_time, "path": f"frames/{filename}"})
                while next_frame_time <= sim_time + 0.001:
                    next_frame_time += 1.0 / CAMERA_HZ

        # Record the disarmed terminal state and final camera sample before
        # leaving the episode. Breaking in the action block made the last
        # state intermittently appear armed despite a successful disarm ACK.
        if finished:
            break

    timeline.stop()
    if backend.px4_tool is not None:
        px4_root = Path(backend.px4_tool.root_fs.name)
        backend.px4_tool.kill_px4()
        time.sleep(0.3)
        ulogs = sorted(px4_root.rglob("*.ulg"))
        if ulogs:
            shutil.copy2(ulogs[-1], episode_dir / "px4.ulg")
    tlog_stream.flush()
    tlog_stream.close()
    gcs.close()

    pd.DataFrame(actions).to_parquet(episode_dir / "joystick.parquet", index=False)
    pd.DataFrame(states).to_parquet(episode_dir / "vehicle_state.parquet", index=False)
    pd.DataFrame(events, columns=["sim_time_s", "type", "payload"]).to_parquet(
        episode_dir / "events.parquet", index=False
    )
    pd.DataFrame(frames).to_parquet(episode_dir / "frames.parquet", index=False)
    export_training_views(episode_dir, frames, actions, mission)

    duration = states[-1]["sim_time_s"] if states else 0.0
    path_length = 0.0
    if len(states) > 1:
        positions = np.asarray([[s["x_enu_m"], s["y_enu_m"], s["z_enu_m"]] for s in states])
        path_length = float(np.linalg.norm(np.diff(positions, axis=0), axis=1).sum())
    status = "success" if finished else "failed"
    manifest = {
        "schema_version": "uav-poc-v2" if args.scene_version == "v2" else "uav-poc-v1",
        "episode_id": args.episode_id,
        "mission_id": mission.get("mission_id"),
        "task_type": mission.get("task_type"),
        "status": status,
        "seed": args.seed,
        "simulator": "NVIDIA Isaac Sim 5.1.0",
        "vehicle_target": "Holybro PX4 Development Kit X500 v2",
        "simulation_vehicle": "Pegasus Iris articulation; X500-v2-class POC proxy",
        "autopilot": "PX4 SITL v1.14.3",
        "controller_interface": "MAVLink MANUAL_CONTROL",
        "camera": {
            "type": "fixed_forward_rgb",
            "hz": CAMERA_HZ,
            "resolution": IMAGE_SIZE,
            "mount_xyz_m": CAMERA_MOUNT_XYZ_M,
            "mount_rpy_deg": CAMERA_MOUNT_RPY_DEG,
            "clipping_range_m": [CAMERA_NEAR_CLIP_M, CAMERA_FAR_CLIP_M],
        },
        "action_hz": ACTION_HZ,
        "duration_s": duration,
        "path_length_m": path_length,
        "frame_count": len(frames),
        "action_count": len(actions),
        "state_count": len(states),
        "last_waypoint_index": waypoint_index,
        "wall_time_s": time.time() - wall_start,
        "environment": environment_metadata,
        "files": {},
    }
    for path in sorted(episode_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            manifest["files"][str(path.relative_to(episode_dir))] = {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
    write_json(episode_dir / "manifest.json", manifest)
    print("EPISODE_RESULT " + json.dumps(manifest), flush=True)
    simulation_app.close()
    if not finished:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
