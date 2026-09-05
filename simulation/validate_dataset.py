#!/usr/bin/env python3
"""Deep validation for the ten-episode UAV simulation proof of concept."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from pymavlink import mavutil
from pyulog import ULog
from validation_contract import check_records, check_export_row, observed_px4_evidence


REQUIRED_FILES = (
    "manifest.json",
    "mission.json",
    "frames.parquet",
    "joystick.parquet",
    "vehicle_state.parquet",
    "events.parquet",
    "mavlink.tlog",
    "px4.ulg",
)
ACTION_COLUMNS = ("roll", "pitch", "yaw", "throttle")
ULOG_TOPICS = ("manual_control_setpoint", "vehicle_status", "actuator_outputs")
FRAME_PATTERN = re.compile(r"^frames/rgb_(\d{12})\.jpg$")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_tlog(path):
    counts = {name: 0 for name in ("HEARTBEAT", "LOCAL_POSITION_NED", "COMMAND_ACK")}
    connection = mavutil.mavlink_connection(str(path), notimestamps=False)
    while True:
        message = connection.recv_match(blocking=False)
        if message is None:
            break
        name = message.get_type()
        if name in counts:
            counts[name] += 1
    connection.close()
    return counts


def validate_ulog(path, actions):
    ulog = ULog(str(path), message_name_filter_list=list(ULOG_TOPICS))
    topics = {}
    for item in ulog.data_list:
        length = len(next(iter(item.data.values()))) if item.data else 0
        topics[item.name] = topics.get(item.name, 0) + length
    datasets = {item.name: item.data for item in ulog.data_list if getattr(item, "multi_id", 0) == 0}
    evidence, errors = observed_px4_evidence(datasets, actions)
    return topics, evidence, errors


def validate_exports(episode, frames, actions, errors):
    result = {}
    frame_paths = set(frames.path)
    frame_lookup = {row["path"]: row for row in frames.to_dict("records")}
    action_records = actions.to_dict("records")
    action_times = actions.sim_time_s.tolist()
    causal = "transmitted_time_s" in actions.columns
    for rate in (2, 5, 10):
        path = episode / "exports" / f"{rate}hz.jsonl"
        if not path.exists() or path.stat().st_size == 0:
            errors.append(f"{episode.name}: missing or empty {rate} Hz export")
            continue
        rows = []
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    errors.append(f"{episode.name}: malformed {rate} Hz export line {line_number}: {exc}")
                    break
        timestamps = np.asarray([row["timestamp_s"] for row in rows], dtype=float)
        gaps = np.diff(timestamps)
        if len(gaps) and float(gaps.min()) < 1.0 / rate - 0.003:
            errors.append(f"{episode.name}: {rate} Hz export contains an oversampled gap")
        expected = max(1, int(round((frames.sim_time_s.iloc[-1] - frames.sim_time_s.iloc[0]) * rate)) + 1)
        if abs(len(rows) - expected) > 2:
            errors.append(f"{episode.name}: {rate} Hz export count {len(rows)} differs from expected {expected}")
        for row in rows:
            issue = check_export_row(row, frame_lookup, action_records, action_times, causal=causal, rate=rate)
            if issue:
                errors.append(f"{episode.name}: {rate} Hz {issue}")
                break
            if row.get("image") not in frame_paths:
                errors.append(f"{episode.name}: {rate} Hz export references a missing frame")
                break
            action = row.get("action", {})
            if set(action) != set(ACTION_COLUMNS) or not all(-1.0 <= float(action[key]) <= 1.0 for key in ACTION_COLUMNS):
                errors.append(f"{episode.name}: invalid action in {rate} Hz export")
                break
        result[f"export_{rate}hz_count"] = len(rows)
    return result


def validate_episode(episode, errors):
    error_start = len(errors)
    for relative in REQUIRED_FILES:
        path = episode / relative
        if not path.exists() or path.stat().st_size == 0:
            errors.append(f"{episode.name}: missing or empty {relative}")
    if any(not (episode / relative).exists() for relative in REQUIRED_FILES):
        return None

    manifest = json.loads((episode / "manifest.json").read_text(encoding="utf-8"))
    mission = json.loads((episode / "mission.json").read_text(encoding="utf-8"))
    actions = pd.read_parquet(episode / "joystick.parquet")
    states = pd.read_parquet(episode / "vehicle_state.parquet")
    frames = pd.read_parquet(episode / "frames.parquet")
    events = pd.read_parquet(episode / "events.parquet")

    if manifest.get("status") not in ("success", "failed"):
        errors.append(f"{episode.name}: invalid outcome status={manifest.get('status')}")
    if manifest.get("controller_interface") != "MAVLink MANUAL_CONTROL":
        errors.append(f"{episode.name}: controller interface is not MAVLink MANUAL_CONTROL")
    if manifest.get("vehicle_target") != "Holybro PX4 Development Kit X500 v2":
        errors.append(f"{episode.name}: X500 v2 target missing from manifest")
    if mission.get("seed") != manifest.get("seed"):
        errors.append(f"{episode.name}: mission/manifest seed mismatch")
    split_evidence = "unverified_legacy"
    if "dataset_split" in manifest:
        from dataset_splits import validate_assignments
        assignment = validate_assignments([manifest["dataset_split"]])
        split_evidence = "verified" if assignment["valid"] else "inconsistent"
        errors.extend(f"{episode.name}: {issue}" for issue in assignment["errors"])
    if manifest.get("schema_version") == "uav-poc-v2":
        environment = manifest.get("environment", {})
        clipping_range = manifest.get("camera", {}).get("clipping_range_m", [])
        camera_mount = manifest.get("camera", {}).get("mount_xyz_m", [])
        if environment.get("environment_version") != "mountain-valley-v2":
            errors.append(f"{episode.name}: v2 environment metadata missing")
        if environment.get("asset_source") != "Poly Haven" or environment.get("asset_license") != "CC0 1.0 Universal":
            errors.append(f"{episode.name}: v2 asset provenance/license missing")
        if environment.get("asset_count", 0) < 17:
            errors.append(f"{episode.name}: v2 asset inventory is incomplete")
        if len(clipping_range) != 2 or float(clipping_range[1]) < 2000.0:
            errors.append(f"{episode.name}: outdoor camera far plane is too short")
        if environment.get("distant_terrain_extent_m", 0) < 2000.0:
            errors.append(f"{episode.name}: distant terrain envelope is missing")
        if len(camera_mount) != 3 or float(camera_mount[2]) < 0.25:
            errors.append(f"{episode.name}: camera mount can intersect terrain at touchdown")
        clearing = environment.get("launch_clearing_radius_m", {})
        if clearing.get("trees", 0) < 75.0 or clearing.get("groundcover", 0) < 50.0:
            errors.append(f"{episode.name}: launch clearing is too small")

    landing_index = mission.get("landing_index")
    waypoints = mission.get("waypoints_enu_m", [])
    if not isinstance(landing_index, int) or landing_index != len(waypoints) - 1:
        errors.append(f"{episode.name}: invalid landing waypoint definition")

    frame_files = sorted((episode / "frames").glob("*.jpg"))
    if len(frame_files) != len(frames) or len(frames) != manifest.get("frame_count"):
        errors.append(f"{episode.name}: frame count mismatch")
    if len(actions) != manifest.get("action_count") or len(states) != manifest.get("state_count"):
        errors.append(f"{episode.name}: table count mismatch")
    if not len(frames) or not len(actions) or not len(states):
        errors.append(f"{episode.name}: an aligned table is empty")
        return None

    frame_times = frames.sim_time_s.to_numpy(dtype=float)
    action_times = actions.sim_time_s.to_numpy(dtype=float)
    state_times = states.sim_time_s.to_numpy(dtype=float)
    errors.extend(f"{episode.name}: {issue}" for issue in check_records(
        actions.to_dict("records"), frames.to_dict("records"), states.to_dict("records")))
    frame_gaps = np.diff(frame_times)
    action_gaps = np.diff(action_times)
    state_gaps = np.diff(state_times)
    if np.any(frame_gaps <= 0) or (len(frame_gaps) and float(frame_gaps.max()) > 0.105):
        errors.append(f"{episode.name}: RGB timing is not monotonic 10 Hz")
    if np.any(action_gaps <= 0) or (len(action_gaps) and float(action_gaps.max()) > 0.04):
        errors.append(f"{episode.name}: action timing exceeds one physics-tick tolerance")
    if np.any(state_gaps <= 0) or (len(state_gaps) and float(state_gaps.max()) > 0.04):
        errors.append(f"{episode.name}: state timing exceeds one physics-tick tolerance")
    if len(frame_gaps) and not math.isclose(float(np.median(frame_gaps)), 0.1, abs_tol=0.002):
        errors.append(f"{episode.name}: median RGB period is not 100 ms")
    if len(action_gaps) and not math.isclose(float(np.median(action_gaps)), 0.02, abs_tol=0.002):
        errors.append(f"{episode.name}: median action period is not 20 ms")

    for column in ACTION_COLUMNS:
        values = actions[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(np.abs(values) > 1.000001):
            errors.append(f"{episode.name}: {column} action is non-finite or outside [-1, 1]")
    # The legacy mode column was a constant, not an observation. Use ULog below.
    if not np.all(actions["buttons"].to_numpy() == 0):
        errors.append(f"{episode.name}: unexpected scripted button value")
    positions = states[["x_enu_m", "y_enu_m", "z_enu_m"]].to_numpy(dtype=float)
    actual_length = float(np.linalg.norm(np.diff(positions, axis=0), axis=1).sum())
    if not math.isclose(actual_length, float(manifest.get("path_length_m", -1)), abs_tol=0.01, rel_tol=1e-5):
        errors.append(f"{episode.name}: manifest path length differs from recorded positions")
    if not math.isclose(float(state_times[-1]), float(manifest.get("duration_s", -1)), abs_tol=0.04):
        errors.append(f"{episode.name}: manifest duration differs from terminal state timestamp")
    from mission_contract import evaluate_mission
    mission_evaluation = evaluate_mission(mission, states.to_dict("records"))
    if manifest.get("status") == "success" and mission_evaluation.get("verified") and not mission_evaluation.get("success", False):
        errors.append(f"{episode.name}: claimed success contradicts recorded mission geometry/terminal state")
    collision_evaluation = {"success": False, "verified": False,
                            "reason": "legacy recording has no contact monitor evidence"}
    contact_path = episode / "physics_contacts.jsonl"
    if contact_path.exists() or "collision_evidence" in manifest:
        if not contact_path.exists() or "collision_evidence" not in manifest:
            errors.append(f"{episode.name}: contact stream and monitor metadata must both be present")
        else:
            from contact_recorder import evaluate_contacts
            with contact_path.open(encoding="utf-8") as stream:
                contacts = [json.loads(line) for line in stream if line.strip()]
            collision_evaluation = evaluate_contacts(contacts, states.to_dict("records"), manifest["collision_evidence"])
            errors.extend(f"{episode.name}: invalid contact evidence: {issue}" for issue in collision_evaluation.get("errors", []))
            if manifest.get("status") == "success" and collision_evaluation.get("verified") and not collision_evaluation.get("success"):
                errors.append(f"{episode.name}: claimed success contradicts recorded physical collisions")

    image_stds = []
    sample_indices = set(np.linspace(0, len(frame_files) - 1, min(64, len(frame_files)), dtype=int))
    for index, frame_file in enumerate(frame_files):
        relative = f"frames/{frame_file.name}"
        match = FRAME_PATTERN.match(relative)
        if not match:
            errors.append(f"{episode.name}: malformed frame filename {frame_file.name}")
            continue
        try:
            with Image.open(frame_file) as image:
                if image.size != (640, 360) or image.mode != "RGB":
                    errors.append(f"{episode.name}: unexpected image shape/mode in {frame_file.name}")
                image.load()
                if index in sample_indices:
                    image_stds.append(float(np.asarray(image, dtype=np.float32).std()))
        except Exception as exc:
            errors.append(f"{episode.name}: corrupt frame {frame_file.name}: {exc}")
            break
    if image_stds and float(np.median(image_stds)) < 2.0:
        errors.append(f"{episode.name}: sampled RGB frames are predominantly near-uniform")
    for _, frame in frames.iterrows():
        match = FRAME_PATTERN.match(str(frame.path))
        if not match or abs(int(match.group(1)) / 1_000_000.0 - float(frame.sim_time_s)) > 1.1e-6:
            errors.append(f"{episode.name}: frame filename/timestamp mismatch")
            break

    actual_files = {
        str(path.relative_to(episode)): path
        for path in episode.rglob("*")
        if path.is_file() and path.name not in ("manifest.json", "validation_summary.json", "publication.json")
    }
    manifest_files = manifest.get("files", {})
    if set(actual_files) != set(manifest_files):
        errors.append(f"{episode.name}: manifest file inventory mismatch")
    else:
        for relative, path in actual_files.items():
            record = manifest_files[relative]
            if path.stat().st_size != record.get("bytes") or sha256(path) != record.get("sha256"):
                errors.append(f"{episode.name}: size/checksum mismatch for {relative}")
                break

    tlog_counts = validate_tlog(episode / "mavlink.tlog")
    if tlog_counts["HEARTBEAT"] < 50 or tlog_counts["LOCAL_POSITION_NED"] < 100:
        errors.append(f"{episode.name}: MAVLink telemetry log lacks required flight telemetry")
    ulog_topics, px4_evidence, px4_errors = validate_ulog(episode / "px4.ulg", actions.to_dict("records"))
    errors.extend(f"{episode.name}: {issue}" for issue in px4_errors)
    if any(ulog_topics.get(topic, 0) < 100 for topic in ULOG_TOPICS):
        errors.append(f"{episode.name}: PX4 ULog lacks manual-control, status, or actuator evidence")

    export_counts = validate_exports(episode, frames, actions, errors)
    return {
        "episode": episode.name,
        "episode_id": manifest.get("episode_id", episode.name),
        "config_hash": manifest.get("config_hash"),
        "data_valid": len(errors) == error_start,
        "mission_success": bool(mission_evaluation.get("success") and mission_evaluation.get("verified")
                                and collision_evaluation.get("success") and collision_evaluation.get("verified")),
        "mission_evaluation": mission_evaluation,
        "px4_evidence": px4_evidence,
        "collision_evaluation": collision_evaluation,
        "collision_evidence": "verified_collidable_geometry" if collision_evaluation.get("verified") else "unverified_contact_monitor",
        "camera_freshness": "verified_capture_ids" if "capture_frame_id" in frames.columns else "unverified_legacy_capture_time",
        "transmission_metadata": "recorded" if "transmitted_time_s" in actions.columns else "unverified_legacy",
        "split_evidence": split_evidence,
        "seed": manifest["seed"],
        "mission_id": mission.get("mission_id"),
        "task_type": mission.get("task_type"),
        "instruction": mission.get("instruction"),
        "lighting_variant": int(manifest["seed"]) % 3,
        "duration_s": manifest["duration_s"],
        "path_length_m": manifest["path_length_m"],
        "frames": len(frames),
        "actions": len(actions),
        "rgb_median_gap_s": float(np.median(frame_gaps)) if len(frame_gaps) else None,
        "rgb_max_gap_s": float(frame_gaps.max()) if len(frame_gaps) else None,
        "action_median_gap_s": float(np.median(action_gaps)) if len(action_gaps) else None,
        "action_max_gap_s": float(action_gaps.max()) if len(action_gaps) else None,
        "sampled_rgb_median_std": float(np.median(image_stds)) if image_stds else None,
        "mavlink_heartbeat_count": tlog_counts["HEARTBEAT"],
        "mavlink_position_count": tlog_counts["LOCAL_POSITION_NED"],
        "px4_manual_control_samples": ulog_topics.get("manual_control_setpoint", 0),
        "px4_actuator_samples": ulog_topics.get("actuator_outputs", 0),
        "storage_bytes": sum(path.stat().st_size for path in actual_files.values()) + (episode / "manifest.json").stat().st_size,
        "status": manifest["status"],
        **export_counts,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", nargs="?")
    parser.add_argument("--episode", action="append", default=[], help="Validate this explicit attempt only; repeatable")
    parser.add_argument("--expected", type=int, help="Optional aggregate count gate")
    parser.add_argument("--output", type=Path, help="JSON report destination; otherwise stdout only for explicit attempts")
    parser.add_argument("--require-success", action="store_true", help="Require verified mission success and PX4 receipt for expert publication")
    parser.add_argument("--min-lighting-variants", type=int, default=0)
    args = parser.parse_args()
    if not args.dataset_root and not args.episode:
        parser.error("provide dataset_root or at least one --episode")
    if args.dataset_root and args.episode:
        parser.error("choose dataset_root or explicit --episode paths, not both")
    root = Path(args.dataset_root) if args.dataset_root else None
    rows = []
    errors = []
    episode_dirs = ([Path(p) for p in args.episode] if args.episode else
                    sorted(path for path in root.glob("episode-*") if path.is_dir()))
    if len({p.resolve() for p in episode_dirs}) != len(episode_dirs):
        parser.error("duplicate episode paths")
    if not episode_dirs:
        errors.append("no episodes selected")
    if args.expected is not None and len(episode_dirs) != args.expected:
        errors.append(f"expected {args.expected} episodes, found {len(episode_dirs)}")
    for episode in episode_dirs:
        try:
            row = validate_episode(episode, errors)
            if row is not None:
                rows.append(row)
                if args.require_success:
                    if not row["mission_success"] or row["status"] != "success" or not row["mission_evaluation"].get("verified"):
                        errors.append(f"{episode.name}: expert publication requires mission success")
                    if any(row["px4_evidence"].get(key) != "verified" for key in ("mode", "control_receipt")):
                        errors.append(f"{episode.name}: expert publication requires independently verified PX4 mode and controls")
                    if row["camera_freshness"] != "verified_capture_ids" or row["transmission_metadata"] != "recorded":
                        errors.append(f"{episode.name}: expert publication requires sensor capture IDs and explicit transmission metadata")
                    if row["split_evidence"] != "verified":
                        errors.append(f"{episode.name}: expert publication requires a frozen ancestry split assignment")
                    if not row["collision_evaluation"].get("verified") or not row["collision_evaluation"].get("success"):
                        errors.append(f"{episode.name}: expert publication requires verified collision-free contact evidence")
        except Exception as exc:
            errors.append(f"{episode.name}: validator exception: {type(exc).__name__}: {exc}")

    identities = [row["episode_id"] for row in rows]
    if len(identities) != len(set(identities)):
        errors.append("episode instance IDs are not unique")
    if len({row["lighting_variant"] for row in rows}) < args.min_lighting_variants:
        errors.append(f"fewer than {args.min_lighting_variants} lighting variants represented")

    summary = {
        "validator_version": "uav-sim-v3-validator",
        "status": "pass" if not errors else "fail",
        "episode_count": len(rows),
        "valid_data_count": sum(row["data_valid"] for row in rows),
        "successful_mission_count": sum(row["mission_success"] for row in rows),
        "episodes": rows,
        "errors": errors,
    }
    destination = args.output or (root / "validation_summary.json" if root else None)
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(destination)
    if root:
        pd.DataFrame(rows).to_csv(root / "dataset_summary.csv", index=False)
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
