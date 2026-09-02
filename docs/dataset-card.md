# UAV Natural Valley V2 Launch-Fixed Dataset Card

## Dataset

- Name: `natural-valley-v2-launch-fixed`
- Location on AP: `/mnt/frtn/uav-sim/datasets/natural-valley-v2-launch-fixed`
- Generated: 2026-09-02
- Simulator: NVIDIA Isaac Sim 5.1.0 with Pegasus Simulator 5.1.0
- Autopilot: PX4 SITL v1.14.3
- Hardware target: Holybro PX4 Development Kit - X500 v2
- Simulated vehicle: Pegasus Iris articulation used as an X500 v2-class dynamics proxy
- Control interface: MAVLink `MANUAL_CONTROL` in PX4 Position mode
- Validator: `uav-sim-v2-validator`
- Environment revision: `horizon-fix-v3-launch-pad`
- Camera clipping range: 0.05–5,000 m
- Prior release: [`natural-valley-v2-sample.tar.zst`](https://github.com/YerevaNN/VLN-Simulations/releases/download/v0.1.0/natural-valley-v2-sample.tar.zst) predates this horizon correction

## Content

Ten deterministic-seed episodes execute ten different natural-language missions in one comprehensive mountain valley. A 1.3 km-square high-detail collision mesh is enclosed by a 4.8 km-square visual terrain ring. The fixed forward RGB camera records at 10 Hz, while normalized scripted-expert gamepad actions and privileged vehicle state are recorded at 50 Hz. Raw MAVLink telemetry and native PX4 ULogs are retained.

Aggregate validated content:

| Measure | Value |
| --- | ---: |
| Episodes | 10 |
| Unique mission IDs | 10 |
| Unique instructions | 10 |
| Successful episodes | 10 |
| Generation retries | 0 |
| Simulated duration | 1,943.46 s |
| Cumulative path | 6,361.10 m |
| RGB frames | 18,968 |
| Joystick actions | 96,642 |
| Aligned 2 Hz examples | 3,795 |
| Aligned 5 Hz examples | 9,483 |
| Aligned 10 Hz examples | 18,958 |
| Dataset bytes | 1,654,469,668 |
| Reusable asset pack | 499 MB |

The validator returned `pass` with no errors after decoding every image, verifying every manifest checksum, checking timing and action bounds, parsing all aligned exports, inspecting MAVLink and ULog evidence, and requiring the long-range camera, distant terrain envelope, elevated camera mount, and launch clearing. A contact-sheet review of every first and last frame also confirmed that no episode starts or ends inside vegetation. The earlier datasets remain intact on AP.

## Missions

| Episode | Mission ID | Simulated time | Path |
| ---: | --- | ---: | ---: |
| 0 | `upper-river-waterfall-recon` | 200.30 s | 674.66 m |
| 1 | `western-forest-deadwood-survey` | 176.86 s | 548.59 m |
| 2 | `stone-cairn-photogrammetry-orbit` | 215.24 s | 639.07 m |
| 3 | `footbridge-structural-inspection` | 140.70 s | 290.99 m |
| 4 | `north-slope-rockslide-assessment` | 193.68 s | 635.24 m |
| 5 | `south-meadow-search-grid` | 211.92 s | 750.27 m |
| 6 | `fire-lookout-perimeter-check` | 175.66 s | 500.10 m |
| 7 | `confluence-branch-mapping` | 160.70 s | 511.97 m |
| 8 | `southern-cliff-gate-transit` | 195.52 s | 731.38 m |
| 9 | `multi-landmark-valley-patrol` | 272.88 s | 1,078.84 m |

The full instructions, task types, named landmarks, subgoals, and ENU waypoint routes are stored in each episode's `mission.json`.

## Environment And Assets

The scene includes collision terrain, a coarse distant mountain ring, an extended winding river and pebble bed, background forest bands, explicit instancer bounds, mountain walls, trees, saplings, grasses, ferns, shrubs, deadwood, stumps, boulders, mossy rocks, a bridge, cairn, lookout, waterfall, rockslide, cliff gate, survey marker, mountain HDR environment, and deterministic lighting variation.

The 18-asset source pack is pinned at `/mnt/frtn/uav-sim/assets/polyhaven-v2`. Its `asset_manifest.json` records source URLs, authors, file hashes, sizes, and license. Poly Haven assets are released under [CC0 1.0 Universal](https://polyhaven.com/license). Powered by Poly Haven.

## Episode Files

Each `episode-NNN` directory contains:

- `manifest.json`: configuration, versions, summary, environment provenance, file sizes, and SHA-256 checksums;
- `mission.json`: unique language instruction, task type, landmarks, subgoals, and ENU route;
- `frames/*.jpg` and `frames.parquet`: timestamped 640 × 360 RGB observations;
- `joystick.parquet`: normalized roll, pitch, yaw, and throttle actions;
- `vehicle_state.parquet`: privileged pose, velocity, attitude, arming, and route progress;
- `events.parquet`: PX4 acknowledgements, status, waypoint, and touchdown events;
- `mavlink.tlog` and `px4.ulg`: raw MAVLink and native PX4 telemetry;
- `exports/{2,5,10}hz.jsonl`: aligned training examples at three sampling rates.

Dataset-level `dataset_summary.csv` and `validation_summary.json` provide the aggregate report and validation result.

## Playback And Reproduction

The synchronized viewer is hosted at [http://ap.yc2.io:8787](http://ap.yc2.io:8787). It plays each mission's text, RGB frames, route, subgoals, virtual gamepad inputs, and telemetry. Its semantic mission map reconstructs the actual episode-seeded river, trees, groundcover, rocks, debris, rockslide, cliffs, and named landmarks using the same placement sequence and route-clearance rules as the Isaac scene.

The repository launcher is [`scripts/run_batch.sh`](../scripts/run_batch.sh). It downloads pinned assets if absent, selects the configured GPU, resumes idempotently, retries episode-generation failures, validates the entire dataset, and exits nonzero on any failed quality gate.

## Intended Use And Limitations

This is a proof-of-concept dataset for pipeline development, action/observation tokenization, temporal alignment experiments, and small VLM training smoke tests. It is not large enough for post-training by itself and is not evidence of real-world flight safety.

The vehicle is still an Iris-derived X500 v2-class proxy; water and vegetation are static; terrain is curated rather than reconstructed from a surveyed location; the expert mimics gamepad control but has not yet been calibrated against human demonstrations; and the single body-fixed camera can still produce ground- or sky-heavy moments during strong attitude changes.
