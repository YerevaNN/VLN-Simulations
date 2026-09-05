"""CPU-only semantic checks: no simulator import or generated flags needed."""
import ast
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation"))
from mission_contract import evaluate_mission

def definitions():
    source = Path(__file__).resolve().parents[1] / "simulation" / "natural_valley.py"
    tree = ast.parse(source.read_text())
    names = {"river_y", "terrain_height", "orbit", "finish_route", "mission_definition"}
    module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names],
                        type_ignores=[])
    namespace = {"math": math}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace

def trace(mission):
    rows = []
    previous = (0,0,0.15)
    targets = mission["waypoints_enu_m"]
    for target in targets:
        steps = max(2, int(math.dist(previous[:3], target[:3]) / 0.8))
        for step in range(1, steps + 1):
            point = [previous[j] + (target[j]-previous[j])*step/steps for j in range(3)]
            rows.append(dict(sim_time_s=len(rows)*0.02, x_enu_m=point[0],
                             y_enu_m=point[1], z_enu_m=point[2], vx_enu_mps=0,
                             vy_enu_mps=0, vz_enu_mps=0, armed=True, waypoint_index=-100))
        previous = target
    for _ in range(80):
        rows.append(dict(rows[-1], sim_time_s=len(rows)*0.02, armed=False))
    return rows

class MissionContractTests(unittest.TestCase):
    def setUp(self):
        self.defs = definitions()

    def test_all_navigation_families_have_fulfillable_contracts(self):
        for i in range(10):
            with self.subTest(i=i):
                mission = self.defs["mission_definition"](i, 5200+i)
                outcome = evaluate_mission(mission, trace(mission))
                self.assertTrue(outcome["verified"])
                self.assertTrue(outcome["success"], outcome)
                instruction = mission["instruction"].lower()
                for false_claim in ("beneath", "confluence", "stream branch", "imaging",
                                    "photograph", "keeping the cabin in view", "visual search"):
                    self.assertNotIn(false_claim, instruction)

    def test_generated_progress_flags_do_not_establish_success(self):
        mission = self.defs["mission_definition"](0,5200)
        rows = trace(mission)
        for row in rows:
            row.update(x_enu_m=0,y_enu_m=0,z_enu_m=.15,waypoint_index=999,armed=False)
        self.assertFalse(evaluate_mission(mission, rows)["success"])

    def test_bridge_clearance_independent_of_waypoint_progress(self):
        mission = self.defs["mission_definition"](0,5200)
        predicate = next(p for p in mission["mission_contract"]["predicates"] if p["type"]=="above_bridge")
        i = predicate["waypoint_index"]
        target = list(mission["waypoints_enu_m"][i])
        target[2] = predicate["deck_top_z_m"] - 1
        mission["waypoints_enu_m"][i] = target
        result = evaluate_mission(mission, trace(mission))
        bridge = next(p for p in result["predicates"] if p["type"]=="above_bridge")
        self.assertFalse(bridge["passed"])

    def test_route_near_bridge_does_not_prove_crossing_above_it(self):
        mission = self.defs["mission_definition"](0,5200)
        predicate = next(p for p in mission["mission_contract"]["predicates"] if p["type"]=="above_bridge")
        index = predicate["waypoint_index"]
        target = list(mission["waypoints_enu_m"][index])
        target[1] += 9
        mission["waypoints_enu_m"][index] = target
        outcome = evaluate_mission(mission, trace(mission))
        bridge = next(p for p in outcome["predicates"] if p["type"]=="above_bridge")
        self.assertFalse(bridge["passed"])

    def test_disarmed_and_stable_terminal_state_required(self):
        mission = self.defs["mission_definition"](5,5205)
        rows = trace(mission)
        rows[-1]["armed"] = True
        self.assertFalse(evaluate_mission(mission, rows)["success"])

    def test_duplicate_time_rejected(self):
        mission = self.defs["mission_definition"](5,5205)
        rows = trace(mission)
        rows[1]["sim_time_s"] = rows[0]["sim_time_s"]
        self.assertFalse(evaluate_mission(mission, rows)["success"])

    def test_repeated_family_has_unique_instance_identifier(self):
        first = self.defs["mission_definition"](0,5200)
        second = self.defs["mission_definition"](10,5210)
        self.assertEqual(first["mission_family_id"],second["mission_family_id"])
        self.assertNotEqual(first["mission_id"],second["mission_id"])

    def test_legacy_contract_is_explicitly_unverified(self):
        mission = self.defs["mission_definition"](5,5205)
        mission.pop("mission_contract")
        outcome = evaluate_mission(mission,trace(mission))
        self.assertTrue(outcome["success"])
        self.assertFalse(outcome["verified"])
        self.assertEqual(outcome["scope"],"legacy_route_only")

if __name__ == "__main__":
    unittest.main()

