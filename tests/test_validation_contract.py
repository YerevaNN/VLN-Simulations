import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation"))
from validation_contract import check_export_row, check_records, observed_px4_evidence


def action(time, value):
    return dict(sim_time_s=time, roll=value, pitch=value / 2, yaw=-value,
                throttle=value / 3, subgoal="navigate")


class ValidationContractTests(unittest.TestCase):
    def test_export_rejects_plausible_but_wrong_command(self):
        actions = [action(0, 0), action(.02, .2)]
        frame = {"path": "frame.jpg", "sim_time_s": .015}
        row = dict(image="frame.jpg", timestamp_s=.015, subgoal="navigate",
                   action={k: actions[1][k] for k in ("roll", "pitch", "yaw", "throttle")})
        self.assertIsNone(check_export_row(row, {"frame.jpg": frame}, actions, [0, .02]))
        self.assertIn("differs", check_export_row(row, {"frame.jpg": frame}, actions, [0, .02], causal=True))
        row["timestamp_s"] = .014
        self.assertIn("timestamp", check_export_row(row, {"frame.jpg": frame}, actions, [0, .02]))

    def test_nonfinite_timing_and_stale_camera(self):
        frames = [dict(path=str(i), sim_time_s=t, observation_time_s=1, capture_frame_id=4) for i, t in enumerate((0, math.nan))]
        errors = check_records([], frames, [])
        self.assertTrue(any("non-finite" in e for e in errors))
        self.assertTrue(any("stale" in e for e in errors))

    def test_observed_receipt_and_mode(self):
        actions = [action(i * .02, i / 100) for i in range(30)]
        controls = {k: [row[k] for row in actions] for k in ("roll", "pitch", "yaw", "throttle")}
        datasets = {"manual_control_setpoint": controls, "vehicle_status": {"nav_state": [2] * 30, "arming_state": [2] * 30}}
        evidence, errors = observed_px4_evidence(datasets, actions)
        self.assertEqual(errors, [])
        self.assertEqual(evidence["control_receipt"], "verified")
        self.assertEqual(evidence["mode"], "verified")
        # A valid recording of a failsafe is not corrupt data, but cannot be an expert demonstration.
        datasets["vehicle_status"]["nav_state"][-1] = 4
        self.assertEqual(observed_px4_evidence(datasets, actions)[0]["mode"], "non_posctl_observed")
        controls["yaw"] = [0.9] * 30
        evidence, errors = observed_px4_evidence(datasets, actions)
        self.assertEqual(evidence["control_receipt"], "inconsistent")
        self.assertTrue(errors)

    def test_no_evidence_is_not_verification(self):
        evidence, errors = observed_px4_evidence({}, [])
        self.assertEqual(evidence["mode"], "unverified")
        self.assertEqual(evidence["control_receipt"], "unverified")
        self.assertEqual(errors, [])

    def test_wire_conversion_mismatch(self):
        row = action(0, 0)
        row.update(decision_time_s=0, transmitted_time_s=0, transmitted_x=0,
                   transmitted_y=400, transmitted_r=0, transmitted_z=500)
        self.assertTrue(any("MANUAL_CONTROL" in e for e in check_records([row], [], [])))

    def test_causal_chunks_cover_actual_future_commands(self):
        from recording import training_rows
        actions = [action(i * .02, i / 100) for i in range(30)]
        frame = {"sim_time_s": .015, "path": "frame.jpg"}
        row = next(training_rows([frame], actions, "navigate", 1, 5))
        args = ({"frame.jpg": frame}, actions, [r["sim_time_s"] for r in actions])
        self.assertIsNone(check_export_row(row, *args, causal=True, rate=5))
        row["action_chunk"].pop()
        self.assertIn("omits", check_export_row(row, *args, causal=True, rate=5))

    def test_sensor_lag_uses_observation_availability(self):
        from recording import training_rows
        actions = [action(i * .02, i / 100) for i in range(30)]
        frame = {"sim_time_s": .015, "observation_time_s": .055, "path": "frame.jpg"}
        row = next(training_rows([frame], actions, "navigate", 1, 5))
        args = ({"frame.jpg": frame}, actions, [r["sim_time_s"] for r in actions])
        self.assertEqual(row["timestamp_s"], .015)
        self.assertEqual(row["decision_time_s"], .055)
        self.assertEqual(row["action_time_s"], .04)
        self.assertEqual(row["action_chunk"][0]["timestamp_s"], .06)
        self.assertAlmostEqual(row["action_chunk_end_s"], .255)
        self.assertIsNone(check_export_row(row, *args, causal=True, rate=5))
        row["action"] = {k: actions[0][k] for k in ("roll", "pitch", "yaw", "throttle")}
        self.assertIn("differs", check_export_row(row, *args, causal=True, rate=5))
        row["decision_time_s"] = .015
        self.assertIn("availability", check_export_row(row, *args, causal=True, rate=5))


if __name__ == "__main__":
    unittest.main()
