#!/usr/bin/env python3
"""Finalize one private attempt in a clean CPU interpreter (no Isaac imports)."""
import hashlib
import json
import sys
import time
from pathlib import Path
from recording import training_rows


def finalize(episode_dir):
    import pandas as pd
    episode_dir = Path(episode_dir)
    pending = episode_dir / "postprocess_input.json"
    payload = json.loads(pending.read_text())
    manifest = payload["manifest"]
    mission = json.loads((episode_dir / "mission.json").read_text())
    actions = pd.read_parquet(episode_dir / "joystick.parquet").to_dict("records")
    frames = pd.read_parquet(episode_dir / "frames.parquet").to_dict("records")
    for rate in (2, 5, 10):
        output = episode_dir / "exports" / f"{rate}hz.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as stream:
            for row in training_rows(frames, actions, mission["instruction"], episode_dir.name, rate):
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    for path in sorted(episode_dir.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "manifest.json.tmp", "postprocess_input.json"):
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b""):
                    digest.update(chunk)
            manifest["files"][str(path.relative_to(episode_dir))] = {"bytes":path.stat().st_size,"sha256":digest.hexdigest()}
    now = time.perf_counter()
    manifest["timing"].update(cpu_postprocess_s=now-payload["simulator_released"],
        release_and_recording_drain_s=payload["simulator_released"]-payload["rollout_completed"],
        episode_total_s=now-payload["episode_started"], process_elapsed_s=now-payload["process_started"])
    temporary = episode_dir / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    pending.unlink()
    temporary.replace(episode_dir / "manifest.json")
    print("EPISODE_RESULT " + json.dumps({k:manifest[k] for k in ("episode_id","status","duration_s","frame_count","timing")}),flush=True)
    return manifest

if __name__ == "__main__":
    finalize(sys.argv[1])
