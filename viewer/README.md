# UAV Simulation POC Viewer

Playback UI for the ten-episode Natural Valley v2 UAV simulation dataset. It reads the episode Parquet tables directly and synchronizes each distinct mission instruction, 10 Hz RGB frames, 50 Hz gamepad-style actions, vehicle state, subgoals, and flown trajectory. The mission map deterministically reconstructs the actual per-episode river, vegetation, rocks, debris, cliffs, and named landmarks from the same scene seed and placement rules used by Isaac Sim.

## Deployment

From the repository root, set the dataset location and launch the read-only container:

```bash
DATASET_ROOT=/path/to/natural-valley-v2 PORT=8787 ./scripts/serve_viewer.sh
```

Health endpoint: `http://HOST:8787/api/health`. The reference deployment is available at [ap.yc2.io:8787](http://ap.yc2.io:8787).
