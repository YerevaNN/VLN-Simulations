"""CPU-only API regression tests; run: python -m unittest discover -s viewer."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pyarrow as pa
import pyarrow.parquet as pq


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["UAV_DATASET_ROOT"] = str(self.root)
        spec = importlib.util.spec_from_file_location("viewer_under_test", Path(__file__).with_name("app.py"))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.client = self.module.app.test_client()
        episode = self.root / "episode-1000"
        episode.mkdir()
        (episode / "manifest.json").write_text(json.dumps({"duration_s": 90, "episode_id": "episode-1000"}))
        (episode / "mission.json").write_text(json.dumps({"seed": 5, "waypoints_enu_m": [[0,0,0]]}))
        (episode / "scene_inventory.json").write_text(json.dumps({"objects": [{"path": "/World/Trees", "positions_enu_m": [[11,22,33]]}], "river": [[0,0],[1,2]]}))
        rows = [{"sim_time_s": i / 50, "path": f"frames/{i}.jpg", "roll": 0., "pitch": 0., "yaw": 0., "throttle": .5, "waypoint_index": 0, "subgoal": "fly", "x_enu_m": float(i), "y_enu_m": 0., "z_enu_m": 1., "vx_enu_mps": 1., "vy_enu_mps": 0., "vz_enu_mps": 0., "roll_rad": 0., "pitch_rad": 0., "yaw_rad": 0., "armed": True, "type": "test", "payload": "{}"} for i in range(4501)]
        for name in ("frames", "joystick", "vehicle_state", "events"):
            pq.write_table(pa.Table.from_pylist(rows), episode / f"{name}.parquet", row_group_size=500)

    def tearDown(self):
        self.temp.cleanup()

    def test_overview_and_recorded_scene(self):
        response = self.client.get("/api/episodes/episode-1000")
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertLessEqual(len(data["states"]), 2001)
        self.assertEqual(data["states"][-1][0], 90)
        self.assertEqual(data["environment_map"]["trees"][0][:2], [11,22])
        self.assertIn("Recorded", data["environment_map"]["provenance"])

    def test_chunk_boundary_and_bounds(self):
        data = self.client.get("/api/episodes/episode-1000/chunks/1").json
        self.assertEqual(data["states"][0][0], 29)
        self.assertLess(data["states"][-1][0], 61)
        self.assertEqual(self.client.get("/api/episodes/episode-1000/chunks/4").status_code, 404)
        self.assertEqual(self.client.get("/api/episodes/not-an-episode").status_code, 404)

    def test_static_export_uses_paginated_chunk_layout(self):
        spec = importlib.util.spec_from_file_location("exporter", Path(__file__).parents[1] / "scripts" / "export_static_viewer.py")
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        output = self.root / "preview"
        def fetch(url):
            response = self.client.get(url.removeprefix("http://localhost"))
            self.assertEqual(response.status_code, 200)
            return response.json
        args = ["export", "--viewer-url", "http://localhost", "--dataset-root", str(self.root), "--viewer-static", str(Path(__file__).with_name("static")), "--output", str(output), "--skip-images"]
        with patch.object(exporter, "fetch_json", fetch), patch("sys.argv", args):
            exporter.main()
        self.assertTrue((output / "api" / "episodes-0.json").exists())
        chunk = json.loads((output / "api" / "episodes" / "episode-1000" / "chunks" / "3.json").read_text())
        self.assertTrue(chunk["frames"][0][1].startswith("frames/episode-1000/"))
        self.assertTrue((output / "app.js").read_text().startswith("window.VIEWER_STATIC = true;"))

    def test_pagination_excludes_incomplete(self):
        (self.root / "episode-999").mkdir()
        for number in (1001,1002):
            path = self.root / f"episode-{number}"
            path.mkdir()
            (path / "manifest.json").write_text("{}")
            (path / "mission.json").write_text("{}")
        page = self.client.get("/api/episodes?limit=2").json
        self.assertEqual([e["id"] for e in page["items"]], ["episode-1000", "episode-1001"])
        self.assertEqual(page["next_offset"], 2)
        self.assertEqual(self.client.get("/api/episodes?offset=2&limit=2").json["next_offset"], None)
        self.assertEqual(self.client.get("/api/episodes?offset=bad").status_code, 400)


if __name__ == "__main__":
    unittest.main()
