import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation"))
from recording import quantize_manual, training_rows, ImageWriter, ParquetRecorder

class RecordingTests(unittest.TestCase):
    def test_quantization_axis_order_and_clamping(self):
        self.assertEqual(quantize_manual([2, -.1239, -.9999, -2]), dict(x=-123,y=1000,z=0,r=-999))
        self.assertEqual(quantize_manual([0,0,0,0])["z"],500)
    def test_causal_hold_and_complete_future_chunk(self):
        actions=[dict(sim_time_s=t,subgoal="go",roll=t,pitch=0,yaw=0,throttle=0) for t in [0,.02,.04,.06,.08,.1,.12]]
        rows=list(training_rows([dict(sim_time_s=.039,path="x")], actions,"go","e",10))
        self.assertEqual(rows[0]["action_time_s"],.02)
        self.assertEqual([x["timestamp_s"] for x in rows[0]["action_chunk"]],[.04,.06,.08,.1])
        self.assertAlmostEqual(rows[0]["action_chunk_duration_s"],.081)
    def test_sensor_latency_moves_decision_origin(self):
        actions=[dict(sim_time_s=t,subgoal="go",roll=t,pitch=0,yaw=0,throttle=0) for t in [0,.02,.04,.06,.08,.1,.12]]
        row=list(training_rows([dict(sim_time_s=.01,observation_time_s=.07,path="x")],actions,"go","e",10))[0]
        self.assertEqual(row["timestamp_s"],.01)
        self.assertEqual(row["decision_time_s"],.07)
        self.assertEqual(row["action_time_s"],.06)
        self.assertEqual([x["timestamp_s"] for x in row["action_chunk"]],[.08,.1])
    def test_clean_cpu_finalizer_publishes_complete_manifest(self):
        import json, subprocess, hashlib, time
        import pandas as pd
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            pd.DataFrame([dict(sim_time_s=t,subgoal="go",roll=0.,pitch=0.,yaw=0.,throttle=0.) for t in [0.,.02,.04]]).to_parquet(root/"joystick.parquet")
            pd.DataFrame([dict(sim_time_s=0.,observation_time_s=.01,path="frames/x.jpg")]).to_parquet(root/"frames.parquet")
            (root/"mission.json").write_text(json.dumps(dict(instruction="go")))
            now=time.perf_counter()
            payload=dict(manifest=dict(episode_id=0,status="failed",duration_s=.04,frame_count=1,timing={},files={}),process_started=now,episode_started=now,rollout_completed=now,simulator_released=now)
            (root/"postprocess_input.json").write_text(json.dumps(payload))
            subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/"simulation/postprocess_episode.py"),d],check=True,stdout=subprocess.DEVNULL)
            result=json.loads((root/"manifest.json").read_text())
            self.assertFalse((root/"postprocess_input.json").exists())
            self.assertEqual(result["files"]["exports/10hz.jsonl"]["sha256"],hashlib.sha256((root/"exports/10hz.jsonl").read_bytes()).hexdigest())
    def test_reset_deadline_kills_stalled_worker(self):
        import os, subprocess, signal
        if os.name != "posix":
            self.skipTest("POSIX worker deadline")
        directory=Path(__file__).resolve().parents[1]/"simulation"
        script="from recording import ResetDeadline; import time\nwith ResetDeadline(.05): time.sleep(10)"
        result=subprocess.run([sys.executable,"-c",script],cwd=directory,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=2)
        self.assertEqual(result.returncode,-signal.SIGALRM)
    def test_before_first_command_is_not_fabricated(self):
        self.assertEqual(list(training_rows([dict(sim_time_s=0,path="x")],[dict(sim_time_s=1)],"go","e",2)),[])
    def test_writer_propagates_errors(self):
        import numpy as np
        writer=ImageWriter(max_pending=1)
        writer.submit("/nonexistent-parent/image.jpg",np.zeros((3,3,3),dtype=np.uint8))
        with self.assertRaises(FileNotFoundError):
            writer.close()
    def test_streamed_rows_round_trip_across_batches(self):
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"rows.parquet"
            writer=ParquetRecorder(path,batch_size=2)
            for i in range(5):
                writer.append(dict(index=i,value=i/2))
            writer.close()
            writer.close()
            self.assertEqual(pq.read_table(path).to_pylist(),[dict(index=i,value=i/2) for i in range(5)])

if __name__ == "__main__":
    unittest.main()
