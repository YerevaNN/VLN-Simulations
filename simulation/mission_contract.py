"""Pure navigation contracts evaluated from recorded simulator state.

No event, waypoint-index or generator success flag is trusted. These contracts do
not certify image visibility, coverage, collision freedom or PX4 command receipt.
"""
import math


def make_contract(mission, bridge_deck_z_m, river_center_y_m):
    route = mission["waypoints_enu_m"]
    tolerances = [3.0 if ("orbit" in p[3] or "circle" in p[3]) else 6.0 for p in route]
    predicates = [{"type": "ordered_waypoints"}, {"type": "terminal_landing",
                   "horizontal_tolerance_m": 2.5, "max_z_m": 0.9,
                   "max_speed_mps": 0.5, "dwell_s": 1.0}]
    start = 0
    while start < len(route):
        label = route[start][3]
        end = start + 1
        while end < len(route) and route[end][3] == label:
            end += 1
        if end - start >= 6 and ("orbit" in label or "circle" in label):
            # The route contains a closed loop followed by one overlap segment.
            ring = route[start:end-2]
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
            cross = ((ring[0][0]-cx)*(ring[1][1]-cy) -
                     (ring[0][1]-cy)*(ring[1][0]-cx))
            predicates.append({"type": "orbit", "label": label,
                               "start_index": start, "end_index": end - 1,
                               "center_enu_m": [cx, cy], "direction": 1 if cross > 0 else -1,
                               "minimum_sweep_rad": 2 * math.pi,
                               "radius_m": math.hypot(ring[0][0]-cx, ring[0][1]-cy),
                               "radial_tolerance_m": 6.0})
        start = end
    for i, point in enumerate(route):
        if abs(point[0]-72) < 0.1 and abs(point[1]-river_center_y_m) < 0.1:
            predicates.append({"type": "above_bridge", "waypoint_index": i,
                               "center_enu_m": [72.0, river_center_y_m],
                               "deck_top_z_m": bridge_deck_z_m, "minimum_clearance_m": 3.0})
    return {"version": 1, "scope": "navigation_only",
            "waypoint_horizontal_tolerances_m": tolerances, "vertical_tolerance_m": 3.0,
            "predicates": predicates,
            "unverified_capabilities": ["camera_visibility", "image_coverage",
                                        "collision_freedom", "PX4_command_application"]}


def evaluate_mission(mission, states):
    """Return independent task outcome; accept a list of state dictionaries."""
    contract = mission.get("mission_contract")
    verified = bool(contract and contract.get("version") == 1)
    route = mission.get("waypoints_enu_m", [])
    scope = contract.get("scope", "navigation_only") if verified else "legacy_route_only"
    if not verified:
        contract = {"waypoint_horizontal_tolerances_m": [6.0] * len(route),
                    "vertical_tolerance_m": 3.0,
                    "predicates": [{"type": "ordered_waypoints"},
                        {"type": "terminal_landing", "horizontal_tolerance_m": 2.5,
                         "max_z_m": 0.9, "max_speed_mps": 0.5, "dwell_s": 1.0}]}
    results = []
    def result(kind, passed, **details):
        results.append({"type": kind, "passed": bool(passed), **details})
    try:
        required = ["sim_time_s", "x_enu_m", "y_enu_m", "z_enu_m",
                    "vx_enu_mps", "vy_enu_mps", "vz_enu_mps"]
        if not route or not states:
            raise ValueError("missing route or recorded states")
        for i, row in enumerate(states):
            if not all(math.isfinite(float(row[k])) for k in required):
                raise ValueError("non-finite recorded state")
            if i and float(row["sim_time_s"]) <= float(states[i-1]["sim_time_s"]):
                raise ValueError("state timestamps must be strictly increasing")
        tolerances = contract["waypoint_horizontal_tolerances_m"]
        hits = {}
        cursor = 0
        # Last point is handled separately by the landing predicate.
        for waypoint, target in enumerate(route[:-1]):
            for index in range(cursor, len(states)):
                row = states[index]
                if (math.hypot(row["x_enu_m"]-target[0], row["y_enu_m"]-target[1]) <= tolerances[waypoint]
                        and abs(row["z_enu_m"]-target[2]) <= contract["vertical_tolerance_m"]):
                    hits[waypoint] = index
                    cursor = index + 1
                    break
            else:
                break
        for predicate in contract["predicates"]:
            kind = predicate["type"]
            if kind == "ordered_waypoints":
                result(kind, len(hits) == len(route)-1, reached=len(hits),
                       expected=len(route)-1,
                       first_missing_index=len(hits) if len(hits) < len(route)-1 else None)
            elif kind == "terminal_landing":
                final = states[-1]
                tail = [r for r in states if r["sim_time_s"] >= final["sim_time_s"]-predicate["dwell_s"]]
                target = route[-1]
                def stable(r):
                    return (math.hypot(r["x_enu_m"]-target[0], r["y_enu_m"]-target[1])
                            <= predicate["horizontal_tolerance_m"]
                            and -0.3 <= r["z_enu_m"] <= predicate["max_z_m"]
                            and math.sqrt(sum(r[k]**2 for k in
                                ("vx_enu_mps","vy_enu_mps","vz_enu_mps"))) <= predicate["max_speed_mps"])
                dwell = final["sim_time_s"]-tail[0]["sim_time_s"]
                passed = (dwell >= predicate["dwell_s"]-0.05 and all(stable(r) for r in tail)
                          and final.get("armed") is not None and not bool(final["armed"])
                          and len(hits) == len(route)-1
                          and tail[0]["sim_time_s"] > states[hits[len(route)-2]]["sim_time_s"])
                result(kind, passed, observed_dwell_s=dwell, final_disarmed=not bool(final.get("armed", True)))
            elif kind == "above_bridge":
                waypoint = predicate["waypoint_index"]
                first = hits.get(max(0, waypoint - 1))
                last = hits.get(min(len(route)-2, waypoint + 1))
                clearances = []
                cx, cy = predicate["center_enu_m"]
                # Recompute a swept crossing of the actual bridge center plane.
                # Reaching a 6 m waypoint ball alone does not mean flying above it.
                if first is not None and last is not None:
                    for a, b in zip(states[first:last], states[first+1:last+1]):
                        dx = b["x_enu_m"] - a["x_enu_m"]
                        if dx <= 0 or not a["x_enu_m"] <= cx <= b["x_enu_m"]:
                            continue
                        fraction = (cx-a["x_enu_m"]) / dx
                        y = a["y_enu_m"] + fraction*(b["y_enu_m"]-a["y_enu_m"])
                        z = a["z_enu_m"] + fraction*(b["z_enu_m"]-a["z_enu_m"])
                        if abs(y-cy) <= 6.5:
                            clearances.append(z-predicate["deck_top_z_m"])
                clearance = max(clearances) if clearances else None
                result(kind, clearance is not None and clearance >= predicate["minimum_clearance_m"],
                       clearance_m=clearance, above_bridge_crossings=len(clearances))
            elif kind == "orbit":
                first, last = hits.get(predicate["start_index"]), hits.get(predicate["end_index"])
                sweep, radial_ok = 0.0, True
                if first is None or last is None:
                    result(kind, False, label=predicate["label"], reason="orbit route incomplete")
                    continue
                cx, cy = predicate["center_enu_m"]
                previous = None
                for row in states[first:last+1]:
                    dx, dy = row["x_enu_m"]-cx, row["y_enu_m"]-cy
                    radial_ok &= abs(math.hypot(dx,dy)-predicate["radius_m"]) <= predicate["radial_tolerance_m"]
                    angle = math.atan2(dy,dx)
                    if previous is not None:
                        sweep += math.atan2(math.sin(angle-previous), math.cos(angle-previous))
                    previous = angle
                directed = sweep * predicate["direction"]
                result(kind, radial_ok and directed >= predicate["minimum_sweep_rad"],
                       label=predicate["label"], directed_sweep_rad=directed, radial_corridor_passed=radial_ok)
            else:
                result(kind, False, reason="unsupported predicate")
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        result("input_validity", False, reason=str(exc))
    return {"success": bool(results) and all(p["passed"] for p in results),
            "verified": verified, "scope": scope, "predicates": results}

