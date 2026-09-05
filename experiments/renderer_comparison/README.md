# Valley renderer comparison

This experiment compares the existing VLN natural valley through Isaac Sim on
AP's RTX A6000 and two H100 rendering paths: Newton's Warp camera renderer and
BEHAVIOR/OmniGibson's Kit renderer settings. It measures image production and
appearance, not policy quality or flight dynamics.

## Backends and provenance

- Isaac Sim 5.1.0 is the runtime already installed on AP. The H100 runtime is a
  private copy of that distribution, including its licenses, outside this repo.
- Newton `6d2ece7c314248960a249ebc46b0dafbb5a89232`, Warp 1.17.0:
  `newton.sensors.SensorTiledCamera`, the compute renderer underlying the Isaac
  Lab Newton/Warp route. This script calls that backend directly; it does not
  claim to execute a complete Isaac Lab task. Isaac Lab is NVIDIA's open-source
  robot-learning framework, with research/community contributors. See its
  [renderer documentation](https://isaac-sim.github.io/IsaacLab/develop/source/overview/core-concepts/renderers.html).
- BEHAVIOR-1K `22d19cd2f99d6ae15dd0fb62e90363410cdd3260`: the exact upstream
  `Simulator._set_renderer_settings` function is extracted and executed with
  `ENABLE_HQ_RENDERING=True`. The default mode is `RealTimePathTracing`.
  The separate `behavior-pathtracing` diagnostic overrides the mode to
  `PathTracing`; it is not the upstream default or a complete BEHAVIOR task.

## Scene and camera controls

The unmodified `simulation/natural_valley.py` at seed 5200 builds one USD stage.
Its source SHA-256 is
`843f0c859a7e001f0b1aed3654d4733575f79a1e530943d365fccc75a064c952`,
identical to the AP source inspected for this experiment. All backends read the
same exported scene and camera file: six static views and a 48-frame camera
replay, at 640 x 360 pixels. Camera coordinates use USD/OpenGL conventions.
The replay does not involve a simulated drone or PX4 controller.

Newton's importer does not expand USD PointInstancers. The adapter expands all
3,019 scene instances into referenced transforms, retaining prototype-local
transforms and instance placement. It enables texture rendering and shadows.
Sun direction is matched, but Newton uses its own illumination model, without
matching the HDRI or radiometric light intensity. Its importer warns that
roughness textures use a scalar fallback. These are fidelity differences to
inspect, not evidence of full RTX parity.

## Running

Set `VLN_COMPARISON_ROOT` to a workspace containing `repo/`,
`assets/polyhaven-v2/`, and the runtime directories. Outputs go to
`comparison/`, caches to `cache/`, and Slurm logs to `logs/`, outside Git.
Prepare the scene with the `isaac-ap` run before submitting H100 jobs.

```bash
sbatch --export=ALL,VLN_COMPARISON_ROOT="$VLN_COMPARISON_ROOT" \
  -p rtx --gres=gpu:rtx_a6000:1 --cpus-per-task=8 --mem=45G --time=00:20:00 \
  -o "$VLN_COMPARISON_ROOT/logs/compare-ap-%j.log" \
  experiments/renderer_comparison/run.slurm isaac-ap

sbatch --export=ALL,VLN_COMPARISON_ROOT="$VLN_COMPARISON_ROOT" \
  -p research --gres=gpu:h100:1 --cpus-per-task=8 --mem=100G --time=00:40:00 \
  -o "$VLN_COMPARISON_ROOT/logs/compare-newton-%j.log" \
  experiments/renderer_comparison/run.slurm newton
```

Use `behavior-hq` or `behavior-pathtracing` instead of `newton` for the Kit
paths. The Python environment needs the pinned Newton checkout, Warp 1.17.0,
usd-core, newton-usd-schemas, NumPy, Pillow, imageio and imageio-ffmpeg.
Kit additionally needs GLU/OpenGL system libraries and writable private caches.

Every successful run writes PNG frames, static-view depth arrays and a manifest
with source hashes, device identity, Slurm ID, settings and frame statistics.
Capture times include settling/sampling and file output; they are not renderer
FPS benchmarks. Startup failures must be reported from logs, not as images.

## Repository preservation

Commit `ef2729b` preserves the pre-existing untracked cluster engineering copy
relative to GitHub's `a6d036c`. Subsequent commits contain this experiment.
The AP working tree and existing dataset/viewer are untouched. Bulk assets,
runtime binaries and generated full-resolution sequences remain outside Git.
