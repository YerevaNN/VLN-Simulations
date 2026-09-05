# Possible Extensions To The UAV Simulation POC

This document is the backlog for capabilities deliberately excluded from the first ten-episode proof of concept. Items should move into the core specification only after the POC is working and a concrete experiment requires them.

The concrete production proposal, including the 10K-hour target, sensor and mission taxonomies, dynamic scenes, simulator allocation, compute budget, and staged execution gates, is maintained in the [10K-hour scale plan](scale-plan.md). This file remains the longer-term extension backlog and should not duplicate that specification.

The `natural-valley-v2` follow-on has now implemented one comprehensive textured mountain-valley environment, 18 pinned CC0 natural assets, dense route-aware vegetation and geology, deterministic lighting variation, and ten distinct language missions. Broader terrain families, weather, moving entities, and real elevation data remain extensions.

## Capture And Sensors

- Add a downward-facing RGB camera for terrain-relative localization and landing.
- Add a controllable gimbal and record gimbal commands separately from vehicle actions.
- Add stereo or depth cameras, lidar, infrared, event cameras, radar, or RF-derived observations.
- Retain lossless or lightly compressed source frames for sensor-model research.
- Increase RGB capture from 10 Hz to 20 or 30 Hz for faster flight or low-level visuomotor policies.
- Record multiple camera exposure models, rolling shutter, motion blur, lens distortion, noise, and compression artifacts.
- Tune the fixed camera mount from an image-information objective and reject or relabel sustained sky-only/ground-only intervals caused by body pitch.

## Environments And Missions

- Generate larger terrain families with new valleys, forests, deserts, snow, coastlines, and rural settlements.
- Import licensed real digital elevation models and satellite-derived textures.
- Add weather, fog, rain, snow, smoke, seasonal variation, day/night cycles, and sun-angle randomization.
- Add moving wildlife, vehicles, people, and other UAVs where a research question requires them.
- Add inspection, search, mapping, target-following, emergency landing, and multi-stage language missions.
- Add GPS-denied segments, communication loss, battery constraints, sensor failures, and PX4 failsafes.

## Operators And Actions

- Fit the scripted expert's smoothing, delay, dead zones, and correction statistics to real gamepad demonstrations.
- Train a learned expert from successful scripted trajectories and later real flights.
- Generate controlled skill levels, hesitations, recoveries, near-misses, and safe failure demonstrations.
- Add intervention trajectories in which an expert corrects a weaker policy.
- Compare continuous joystick actions with discrete action tokens, waypoint actions, and hierarchical subgoals.
- Learn a reusable action tokenizer while preserving the original continuous command stream.

## Scale And Data Quality

- Run multiple headless simulator workers per GPU and across additional RTX hosts.
- Benchmark faster-than-real-time execution without weakening physics, sensor timing, or PX4 lockstep behavior.
- Add automatic scene, mission, and difficulty balancing.
- Detect duplicate and low-information frames before training export while preserving raw archives.
- Add curriculum generation driven by policy failures and coverage gaps.
- Add object storage, checksums, retention tiers, dataset versioning, and lineage tracking for billion-token runs.
- Add dataset cards, licenses, privacy checks, and release-ready subsets.

## Model Training And Evaluation

- Export sequences for continual pretraining, next-action prediction, reasoning traces, and trajectory-level reinforcement learning.
- Generate simulator-verifiable reasoning annotations from mission and privileged state.
- Train at 2 Hz, 5 Hz, and 10 Hz and measure the latency-versus-control tradeoff.
- Test history length, visual-token density, temporal redundancy, and action-window design.
- Maintain unseen terrain, weather, and mission families as fixed evaluation sets.
- Compare scripted, learned, and real operator action distributions.

## Physical X500 v2 Transfer

- Replace the POC's Pegasus Iris articulation proxy with a Holybro X500 v2 USD visual/collision model and X500-specific mass, inertia, rotor, and thrust parameters.
- Measure assembled mass, center of gravity, inertia, motor/propeller thrust curves, battery behavior, and payload.
- Match the real camera model, mount pose, field of view, exposure, latency, and vibration.
- Replace approximate dynamics with identified parameters from safe flight tests.
- Move from SITL to hardware-in-the-loop using the Pixhawk 6C before outdoor autonomous flight.
- Collect a small real calibration set and a fixed real test set.
- Evaluate simulation-only, simulation-plus-real, and real-only training under the same missions.
- Add a second UAV embodiment to study cross-platform action and representation transfer.

## Simulator Alternatives

- Upgrade to Isaac Sim 6 after Pegasus' compatible release is stable and the POC has a regression suite.
- Maintain a faster Gazebo/PX4 backend for high-volume conventional simulation.
- Use Isaac Sim selectively for RTX sensor fidelity and Gazebo for cheaper trajectory diversity.
- Evaluate learned appearance transfer only as an augmentation layer, not as a source of physically guaranteed labels.
