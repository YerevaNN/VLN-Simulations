# Adversarial renderer comparison

The synthetic scene exposes a large real-time/path-tracing appearance mismatch
that the outdoor valley did not make obvious. Nested transparent spheres look
sharp in Isaac 5.1 RaytracedLighting and frosted in both 4.5 and 5.1 PathTracing.
All three completed comparisons here initially used the A6000: this isolates a
mode/settings difference without attributing it to H100 hardware.

## Controls and measurements

`make_stress_scene.py` creates an asset-free USD scene with metallic reflections,
layered opacity, an emissive sphere, thin bars, colored walls and a rectangular
light. Six cameras are each captured three times at 640 × 360. Measurements use
the third capture. The scene uses USD Preview Surface opacity; it is not a
validated physical-glass reference. Pixel differences measure disagreement,
not physical accuracy or statistical significance across environments.

| Comparison, on A6000 | Mean absolute RGB difference (0–255) |
| --- | ---: |
| 5.1 real-time vs 4.5 path tracing, across six views | 12.264–19.809 |
| 5.1 path tracing vs 4.5 path tracing, across six views | 0.071–0.664 |
| Real-time vs 4.5 path tracing, transparency close-up | 18.592 |
| 4.5 path tracing vs high-sample undenoised diagnostic, close-up | 0.008 |

In the transparency close-up, 61.17% of pixels differ by over 10 levels in at
least one channel between real-time and 4.5 path tracing. Consecutive second and
third captures differ by 0.470 levels for real-time and zero for path tracing;
the appearance mismatch is much larger than this observed settling difference.
Identical repeated path-tracing output is not an independent random-seed trial.

The diagnostic requests 64 samples/update, totalSpp 4096 and disabled OptiX
denoising, versus 4 samples/update, totalSpp 256 and enabled denoising. The
blurred appearance persists. These are recorded settings, not instrumented
measurements of the internal renderer's actual sample count or denoiser calls.
Fixed views use 64 subframes for path tracing and 16 for real-time, so this is
not an equal-render-budget comparison or a speed benchmark.

## Runs and limitations

- Bright scene A6000: 246825 (5.1 real-time), 246826 (4.5 path tracing),
  246827 (5.1 path tracing), 246830 (4.5 high-sample undenoised). Each produced
  18 RGB images and 18 depth arrays.
- Dim pilot: A6000 246821–246823 completed. Its illumination was too low for
  convenient material inspection; retained separately under `stress/`.
- H100 gpu03: dim pilot 246820 produced no capture before cancellation;
  bright 246824 failed during SimulationApp startup with ERROR_DEVICE_LOST and
  a segmentation fault. These used shared caches concurrently, so they are
  not clean evidence of a scene-induced hardware failure. Driver 580.105.08
  differs from the successful valley's gpu09 driver 580.173.02.
- H100 retry 246829 used gpu04, driver 590.48.01 and private per-job caches.
  It produced no capture after more than 12 minutes; cancellation was requested.
  This is a no-frame outcome, not proof of a particular shader failure.
- Retry 246828 is queued on gpu09, the successful valley node, awaiting a free
  GPU. The H100 stress comparison remains incomplete until it produces images.

The successful valley run establishes that the pinned 4.5 path works on one
H100 setup. It does not establish compatibility across these other nodes. No
H100-specific visual defect is established by A6000 control images.

## Reproduction and evidence

Sources are in this directory: `make_stress_scene.py`, `stress.slurm`,
`run_isaac.py`, and `analyze_stress.py`. Generate the scene with the standalone
USD Python environment, then run `stress.slurm` through Slurm for each backend
using the GPU partitions documented in README.md. `STRESS_SUITE` selects the
output directory, defaulting to `stress-bright`. The dim pilot was generated
by commit b0a6d8e; subsequent illumination uses 156a434 or later.

Raw data is under `/mnt/weka/hrant/rtx-vln-sample-20260905/stress-bright/`;
logs are under the sibling `logs/`. Manifests, metrics, hashes and a contact
sheet are preserved in [results/stress](results/stress/). The interactive
comparison is generated from the raw outputs by `analyze_stress.py`.
