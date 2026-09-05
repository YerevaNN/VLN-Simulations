"""Simulator-independent checks; absence of evidence is explicitly unverified."""
import bisect
import math
from itertools import product

ACTION_COLUMNS = ("roll", "pitch", "yaw", "throttle")


def check_records(actions, frames, states):
    errors = []
    for name, rows in (("actions", actions), ("frames", frames), ("states", states)):
        times = [float(row["sim_time_s"]) for row in rows]
        if not all(math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
            errors.append(f"{name}: non-finite or non-increasing timestamps")
    fields = ("x_enu_m", "y_enu_m", "z_enu_m", "vx_enu_mps", "vy_enu_mps", "vz_enu_mps")
    if any(not math.isfinite(float(row[field])) for row in states for field in fields):
        errors.append("states: non-finite position or velocity")
    if len({row["path"] for row in frames}) != len(frames):
        errors.append("frames: duplicate image path")
    if frames and "capture_frame_id" in frames[0]:
        # Isaac ReferenceTime identifiers can be structured values serialized as
        # strings. Their order is established by finite, increasing capture time.
        ids = [str(row["capture_frame_id"]) for row in frames]
        if len(set(ids)) != len(ids):
            errors.append("frames: stale or duplicate sensor capture IDs")
        if any(not math.isfinite(float(row["observation_time_s"])) or float(row["observation_time_s"]) + 1e-6 < float(row["sim_time_s"]) for row in frames):
            errors.append("frames: observation available before sensor capture")
    for row in actions:
        if "transmitted_time_s" in row:
            if not all(math.isfinite(float(row[k])) for k in ("decision_time_s", "transmitted_time_s")) or float(row["decision_time_s"]) > float(row["transmitted_time_s"]) + 1e-6:
                errors.append("actions: transmission precedes decision")
                break
            if abs(float(row["sim_time_s"]) - float(row["transmitted_time_s"])) > 1e-6:
                errors.append("actions: source action time differs from transmission time")
                break
            expected = {"pitch": float(row["transmitted_x"]) / 1000,
                        "roll": float(row["transmitted_y"]) / 1000,
                        "yaw": float(row["transmitted_r"]) / 1000,
                        "throttle": float(row["transmitted_z"]) / 500 - 1}
            if any(abs(float(row[k]) - v) > 0.00201 for k, v in expected.items()):
                errors.append("actions: normalized action disagrees with transmitted MANUAL_CONTROL")
                break
    return errors


def check_export_row(row, frames_by_path, actions, action_times, causal=False, rate=None):
    """Reconstruct source selection instead of trusting bounded output values."""
    frame = frames_by_path.get(row.get("image"))
    if frame is None:
        return "export references a missing frame"
    timestamp = float(row["timestamp_s"])
    if not math.isfinite(timestamp) or abs(timestamp - float(frame["sim_time_s"])) > 1e-6:
        return "export timestamp differs from source frame"
    decision_time = float(frame.get("observation_time_s", timestamp)) if causal else timestamp
    if causal and (not math.isfinite(decision_time) or decision_time + 1e-6 < timestamp):
        return "export decision precedes sensor capture or is non-finite"
    if causal:
        recorded_decision = float(row.get("decision_time_s", timestamp))
        if not math.isfinite(recorded_decision) or abs(recorded_decision - decision_time) > 1e-6:
            return "export decision timestamp differs from source observation availability"
    index = bisect.bisect_right(action_times, decision_time) - 1
    if causal:
        if index < 0:
            return "export observation has no preceding transmitted action"
        if decision_time >= action_times[-1]:
            return "export observation has no future recorded control horizon"
    else:
        candidates = [i for i in (index, index + 1) if 0 <= i < len(actions)]
        index = min(candidates, key=lambda i: (abs(action_times[i] - timestamp), i))
    action = row.get("action", {})
    if set(action) != set(ACTION_COLUMNS):
        return "export action has wrong fields"
    if any(not math.isfinite(float(action[k])) or abs(float(action[k]) - float(actions[index][k])) > 1e-6 for k in ACTION_COLUMNS):
        return "export action differs from selected source command"
    if row.get("subgoal") != actions[index].get("subgoal"):
        return "export subgoal differs from selected source command"
    if causal:
        if row.get("alignment") != "latest_transmitted_at_or_before_observation":
            return "export declares an incorrect observation/action alignment"
        if abs(float(row.get("action_time_s", math.nan)) - action_times[index]) > 1e-6 or not math.isfinite(float(row.get("action_time_s", math.nan))):
            return "export action timestamp differs from selected transmission"
        if rate is not None:
            expected_end = min(decision_time + 1 / rate, action_times[-1])
            end = float(row.get("action_chunk_end_s", math.nan))
            duration = float(row.get("action_chunk_duration_s", math.nan))
            if not math.isfinite(end) or not math.isfinite(duration) or abs(end - expected_end) > 1e-6 or abs(duration - (end - decision_time)) > 1e-6:
                return "export action chunk has incorrect horizon"
            chunk = row.get("action_chunk", [])
            start_index = bisect.bisect_right(action_times, decision_time)
            stop_index = bisect.bisect_right(action_times, expected_end - 1e-10)
            source = actions[start_index:stop_index]
            if len(chunk) != len(source):
                return "export action chunk omits or adds transmitted commands"
            for sample, original in zip(chunk, source):
                if not math.isfinite(float(sample["timestamp_s"])) or abs(float(sample["timestamp_s"]) - float(original["sim_time_s"])) > 1e-6 or any(abs(float(sample[k]) - float(original[k])) > 1e-6 or not math.isfinite(float(sample[k])) for k in ACTION_COLUMNS):
                    return "export action chunk differs from transmitted commands"
    return None


def observed_px4_evidence(datasets, actions):
    """Read actual PX4 status and ordered control receipt, without inventing clock alignment.

    ULog may omit individual sends. Check diverse recorded commands in temporal
    order against the transmitted stream, with explicit unmatched counts. This
    proves receipt consistency, not exact application latency or motor causality.
    """
    result = {"mode": "unverified", "control_receipt": "unverified", "application_latency": "unverified"}
    errors = []
    status = datasets.get("vehicle_status", {})
    if "nav_state" in status and "arming_state" in status:
        armed_modes = [int(n) for n, a in zip(status["nav_state"], status["arming_state"]) if int(a) == 2]
        result["armed_nav_states"] = sorted(set(armed_modes))
        if armed_modes:
            result["mode"] = "verified" if set(armed_modes) == {2} else "non_posctl_observed"
    controls = datasets.get("manual_control_setpoint", {})
    # PX4 versions use either x/y/z/r or descriptive field names.
    names = ("y", "x", "r", "z") if "x" in controls else ACTION_COLUMNS
    if all(name in controls for name in names) and actions:
        received = list(zip(*(controls[name] for name in names)))
        if "data_source" in controls:
            result["control_data_sources"] = sorted({int(v) for v in controls["data_source"]})
        expected = [tuple(float(row[k]) for k in ACTION_COLUMNS) for row in actions]
        distinct = []
        for sample_index, values in enumerate(received):
            if "valid" in controls and not controls["valid"][sample_index]:
                continue
            if "data_source" in controls and int(controls["data_source"][sample_index]) not in range(2, 8):
                continue
            sample = tuple(float(v) * 2 - 1 if i == 3 and "x" in controls else float(v) for i, v in enumerate(values))
            if all(math.isfinite(v) for v in sample) and (not distinct or max(abs(a-b) for a,b in zip(sample, distinct[-1])) > 0.005):
                distinct.append(sample)
        cursor = 0
        matched = 0
        tolerance = 0.0041
        buckets = {}
        for i, command in enumerate(expected):
            key = tuple(math.floor(v / tolerance) for v in command)
            buckets.setdefault(key, []).append(i)
        for sample in distinct:
            key = tuple(math.floor(v / tolerance) for v in sample)
            candidates = []
            for delta in product((-1, 0, 1), repeat=4):
                indices = buckets.get(tuple(k+d for k,d in zip(key, delta)), ())
                offset = bisect.bisect_left(indices, cursor)
                while offset < len(indices):
                    candidate = indices[offset]
                    if max(abs(a-b) for a,b in zip(sample, expected[candidate])) <= tolerance:
                        candidates.append(candidate)
                        break
                    offset += 1
            found = min(candidates) if candidates else None
            if found is not None:
                matched += 1
                cursor = found
        result.update(control_distinct_samples=len(distinct), control_matched_samples=matched)
        if len(distinct) >= 10:
            result["control_receipt"] = "verified" if matched / len(distinct) >= 0.95 else "inconsistent"
            if result["control_receipt"] == "inconsistent":
                errors.append("PX4 received controls do not match transmitted command sequence")
    return result, errors
