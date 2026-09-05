# 10K-Hour UAV Dataset Scale Plan

## Objective

Scale the Natural Valley proof of concept into a diverse dataset for continual pretraining and post-training of vision-language-action models that operate a PX4-class UAV at gamepad-command level.

The initial production target is:

- 10,000 accepted hours of simulated flight;
- a compute allocation set by measured accepted-hour cost in the pilot, with no committed 10,000-GPU-hour ceiling;
- roughly 100,000-120,000 episodes spanning seconds to more than an hour;
- 360 million forward RGB frames at 10 Hz;
- 1.8 billion joystick-command samples at 50 Hz;
- enough failed or low-quality raw generation to retain 10,000 hours after filtering.

The target is accepted data, not merely simulator uptime. Model acceptance explicitly: at 80% acceptance, 12,500 raw hours are needed for 10,000 accepted hours (25% overproduction). Measure acceptance by world, mission, failure, backend and sensor tier. Valid failures belong in labeled recovery pools, not automatically in the successful-expert pool.

## Design Principles

1. **Preserve the control boundary.** The learned policy predicts commands available to a human operator; PX4 remains responsible for stabilization and motor-level control.
2. **Separate observation from truth.** Onboard-observable sensors, PX4 estimates, and privileged simulator labels must occupy distinct namespaces so training cannot accidentally leak ground truth.
3. **Measure diversity, not just duration.** Ten thousand hours of repeated straight flight is less useful than a smaller balanced collection with varied perception, actions, mission logic, failures, and recoveries.
4. **Keep source data richer than the first model.** Record high-rate sensors and controls once, then derive lower-rate training views without rerunning simulation.
5. **Split by world and task composition.** Evaluation worlds, assets, weather combinations, and mission compositions must not appear in training.
6. **Make every episode reproducible.** Retain simulator, vehicle, asset, environment, mission, controller, sensor, and random-seed versions.

## Episode Contract

Each episode contains:

- a structured mission graph and one or more natural-language realizations;
- sensor measurements with capture and availability timestamps;
- commands requested by the operator policy and commands delivered to PX4;
- PX4 estimator, controller, actuator, health, and failsafe state;
- privileged simulator truth stored separately;
- environment, weather, vehicle, payload, traffic, and failure configuration;
- outcome, progress, collision, near-miss, recovery, and validation labels;
- complete lineage, checksums, and software versions.

The mission graph is the canonical task representation:

```text
intent -> ordered or conditional subgoals -> constraints
       -> success criteria -> abort criteria
```

Instructions can then be rendered as terse operator commands, detailed procedures, landmark descriptions, conditional requests, mid-flight corrections, or dialogue. Multiple paraphrases of one route add language supervision but do not count as distinct flights.

## Data Layers

### Deployable observations

These are signals that could be available on the physical X500-class vehicle.

| Signal | Source rate | Coverage |
| --- | ---: | --- |
| Forward RGB | 10 Hz | All episodes |
| Accelerometer and gyroscope | 200-400 Hz | All episodes |
| Magnetometer | 50-100 Hz | All episodes |
| Barometric pressure and altitude | 25-50 Hz | All episodes |
| GNSS position, velocity, fix and accuracy | 5-10 Hz | All episodes |
| Downward rangefinder | 20-50 Hz | All episodes |
| Battery voltage, current and estimate | 10-20 Hz | All episodes |
| Downward RGB | 5-10 Hz | Landing, terrain and flow subset |
| Optical flow | 20-50 Hz | GNSS-degraded subset |
| Depth camera | 5-10 Hz | Selected perception subset |
| LiDAR, radar or other expensive sensor | Sensor-specific | Small research subset |
| Gimbal imagery and state | 10-30 Hz | Inspection subset |

GNSS data must include fix type, satellite count, estimated accuracy, latency, dropouts, drift, and multipath-like corruption rather than only perfect position. Cameras should model exposure, motion blur, rolling shutter, compression, noise, vibration, glare, and dropped frames. Sensor clocks and delivery latency should be explicit.

PX4's core sensor set is accelerometer, gyroscope, magnetometer, and barometer; GNSS, rangefinders, and optical flow extend position, landing, terrain-following, and GNSS-denied operation. See the [PX4 sensor documentation](https://docs.px4.io/main/en/getting_started/px4_basic_concepts).

### PX4 controller and estimator state

Record at native or practically lossless rates:

- joystick axes, buttons, flight mode, command latency, and packet loss;
- attitude, rate, position, velocity, and thrust setpoints;
- estimated pose, velocity, attitude, covariances, innovations, and sensor-health flags;
- actuator and motor outputs, saturation, and control-allocation state;
- arming, takeoff, landing, failsafe, battery, and navigation state;
- the current mission subgoal, without future-route leakage.

### Privileged simulator labels

These labels support filtering, auxiliary objectives, rewards, counterfactuals, and analysis but are not ordinary deployment inputs:

- exact pose, velocity, acceleration, wind, and air density;
- metric depth, surface normals, optical flow, semantic and instance masks;
- object identities, poses, visibility, occlusion, and relative geometry;
- terrain-relative altitude, traversability, and nearest-obstacle distance;
- collision contacts, near misses, route clearance, and safety margins;
- ideal route, alternative safe actions, mission progress, and success predicates;
- other agents' intent and future trajectory.

## Mission Taxonomy

Each episode receives one primary mission family and independent modifiers for horizon, difficulty, urgency, traffic, weather, language style, sensor conditions, and required recovery.

| Primary family | Target share | Representative missions |
| --- | ---: | --- |
| Navigation and transit | 20% | Point-to-point, river or trail following, ridge crossing, return-to-home |
| Search and reconnaissance | 18% | Find a person, animal, vehicle, smoke source, damage, or anomaly |
| Inspection | 15% | Orbit and inspect a bridge, tower, cliff, pipeline, building, or canopy |
| Mapping and survey | 12% | Photogrammetry, river mapping, boundary survey, terrain or change survey |
| Emergency and recovery | 15% | GNSS loss, low battery, route blockage, communications loss, sensor fault |
| Tracking and observation | 8% | Follow a person, vehicle, animal, boat, or UAV at a safe distance |
| Precision takeoff and landing | 7% | Confined clearing, sloped terrain, alternate landing-zone selection |
| Payload and logistics | 5% | Delivery, pickup or drop simulation, payload-constrained transit |

At least 35% of episodes should compose several skills. Example: follow a tributary, locate a damaged bridge, inspect both faces, react to a blocked return route, choose an alternate clearing, and land.

## Horizon Mix

Allocate by accepted flight hours while enforcing minimum episode counts:

| Horizon | Share of hours | Approximate episode count |
| --- | ---: | ---: |
| 15 seconds-2 minutes | 10% | 60,000 |
| 2-10 minutes | 30% | 36,000 |
| 10-30 minutes | 40% | 12,000 |
| 30-90 minutes | 20% | 2,000 |

This yields roughly 110,000 episodes. Short episodes provide dense maneuver and recovery supervision; long episodes test memory, progress tracking, replanning, stop decisions, resource management, and instruction completion.

## Environment Diversity

Build 40-60 substantial base worlds and expand them into at least 1,000 validated world variants. Sample combinations rather than taking a full Cartesian product.

- **Biomes:** alpine, temperate and conifer forest, meadow, canyon, desert, snow, wetland, coast, farmland.
- **Topology:** narrow and broad valleys, ridges, saddles, cliffs, plateaus, rivers, lakes, caves, ravines, open plains.
- **Built density:** wilderness, trails, farms, villages, roads, utilities, industrial sites, sparse settlements.
- **Appearance:** seasons, vegetation maturity, terrain materials, asset variants, wetness, snow cover, burn scars.
- **Conditions:** dawn through night, sun angle, cloud, fog, rain, snow, smoke, dust, glare, low contrast.
- **Dynamics:** people, wildlife, road vehicles, boats, other UAVs, moving platforms, falling debris, route changes.
- **Flight dynamics:** wind, gusts, turbulence, temperature, air density, payload, center of gravity, battery and motor variation.
- **Sensor conditions:** calibration error, latency, noise, occlusion, blur, dropped packets, GNSS degradation, magnetic interference.

Freeze world-family partitions before the first training pilot. All descendants of a base world, appearance variants, paraphrases and paired simulator realizations stay in the same partition. Add separately versioned challenge sets for held-out biomes, compositions, failures, weather and vehicle configurations.

Production worlds must be sampled independently of demonstration routes, then routes planned and checked for clearance. Natural Valley retains its explicitly labeled legacy route-cleared distribution until an independent-world planner exists. Scatter seeds are not independent world families.

## Dynamic Scenes And Other UAVs

Isaac Sim supports moving rigid and articulated agents, and Pegasus is built for multiple multirotors. Other UAVs can use three fidelity levels:

1. **Visual-only:** predefined animation for inexpensive distant traffic.
2. **Physics-driven scripted:** multirotor dynamics, wind, and collisions without a separate PX4 process.
3. **Full autonomous:** independent sensors, controller, PX4 SITL instance, and interactive behavior.

Suggested distribution:

- 60%: no other UAV or one to two lightweight traffic drones;
- 25%: three to ten scripted physics-driven drones;
- 10%: a second full PX4 UAV interacting with the primary vehicle;
- 5%: formation, congestion, coordination, or small-swarm scenarios.

Dynamic-agent tasks include crossing traffic, avoidance, following, formation, coordinated search, inspection handoff, disabled-teammate localization, shared target tracking, and congested landing approaches. Isaac provides physics, rendering, and contacts; plausible intent, navigation, right-of-way, and avoidance behavior must be implemented by the dataset generator. Pegasus documents both [multiple aerial vehicles](https://pegasussimulator.github.io/PegasusSimulator/) and [moving-agent controllers](https://pegasussimulator.github.io/PegasusSimulator/source/tutorials/create_simulation_with_people.html).

## Simulator Strategy

Use a common mission, expert, recorder, validator, and episode schema across backends.

### Isaac Sim and Pegasus

Best suited to visually rich VLM data, USD scene composition, domain randomization, privileged perception labels, and RTX sensors. Pegasus connects multirotor sensors and rotor commands to PX4 through a lockstep MAVLink backend. Isaac is the high-fidelity perception generator, but it has high startup and rendering cost and Pegasus is less tightly integrated with PX4 than Gazebo.

### Gazebo

Best suited to high-throughput control, dynamics, sensor degradation, failsafes, counterfactual rollouts, and exact PX4 regression. PX4 provides first-class X500, depth-camera, rangefinder, LiDAR, vision, and gimbal targets, along with lockstep and faster-than-real-time execution. See the [PX4 Gazebo documentation](https://docs.px4.io/main/en/sim_gazebo_gz/).

### AirSim

Legacy AirSim provides Unreal-quality environments, camera APIs, and PX4 integration, but the original Microsoft project is no longer actively developed. It should not be the primary multi-year backend unless the maintained Project AirSim successor is evaluated separately and proves operationally superior.

### Backend selection experiment

Keep Isaac/Pegasus as the initial reference. Add a small Gazebo backend after the correctness and 100-hour gates pass. Pin PX4 commit, Gazebo release, vehicle, parameters, sensor rates and time synchronization behavior; modern Gazebo documentation does not establish compatibility with the current PX4 v1.14.3 setup.

Compare Isaac-only, Gazebo-only and mixed training under both equal generation cost and equal training budget. Report visual-language task success separately from control-only performance. Choose the production mixture from results rather than committing 60-70% to Gazebo. Paired runs share world-family partitions; identical seeds across engines do not imply identical trajectories.

## Operator And Action Diversity

The scripted expert should not produce one unnaturally perfect action distribution.

- 65% clean expert demonstrations;
- 15% competent but human-like control with calibrated delay, smoothing, hesitation, and mild inefficiency;
- 10% injected perturbation followed by recovery;
- 5% weak-policy execution followed by expert intervention;
- 5% safe aborts, unsuccessful missions, and failsafe behavior.

Failed and suboptimal trajectories require explicit outcome and intended-use labels. Preserve continuous controls before deriving discrete tokens, action chunks, waypoints, or hierarchical subgoals. Once the physical X500 is available, fit reaction delay, dead zones, command spectra, camera latency, dynamics, and sensor noise to real operator flights.

## Expensive Sensor Allocation

Basic inertial, GNSS, barometric, range, battery, PX4, and controller logging is inexpensive relative to image rendering. Depth, extra cameras, and RTX sensors should be sampled selectively.

- 70% forward RGB plus ordinary flight sensors;
- 20% add downward RGB, optical flow, and range sensing;
- 8% add depth and semantic or instance labels;
- 2% add LiDAR, radar, or experimental modalities.

The exact percentages should be set after measuring marginal GPU cost and model benefit. Isaac Sim supports independent sensor tick rates, so sensors that do not require every-frame updates should not render every frame.

## Quality And Coverage Gates

Every accepted episode should pass automatic checks for:

- mission completion or correctly labeled failure and abort state;
- collision, near-miss, terrain, geofence, and flight-envelope constraints;
- image decode, exposure, information content, camera motion, and duplicate-frame limits;
- timestamp monotonicity, source frequency, gaps, latency, and cross-modal alignment;
- action validity, variation, saturation, response, and command-to-motion consistency;
- PX4 sensor, estimator, actuator, manual-control, health, and failsafe evidence;
- asset provenance, licenses, file checksums, schema, and reproducibility;
- balance across mission, horizon, world, biome, weather, action, failure, and sensor dimensions.

Use embedding-based visual novelty, action entropy, state coverage, landmark visibility, and mission-graph coverage to suppress redundant generation. Preserve rejected episode metadata and failure reasons without promoting invalid data into expert demonstrations.

## Compute And Storage Budget

The historical horizon dataset reports 1,527.604 wall seconds for 1,941.520 flight seconds: 0.7868 recorded wall-hours per flight-hour. This is a **partial execution timer**, not GPU utilization or full allocated GPU time. It begins after application startup, scene construction and reset and ends before hashing and external validation. Launch-fixed is similar (0.7862).

A later 24-thread qualification attempt recorded 423.08 allocated GPU seconds for 238.06 accepted flight seconds (1.777 GPU-hours per accepted hour), with 6.92 seconds of CPU validation. This is one short successful attempt, excludes separate debugging datasets, and does not estimate production yield. Its startup (86.37 s), setup (55.06 s) and release/recording drain (49.47 s) demonstrate why rollout-only timing is insufficient. See [engineering verification](engineering-notes.md#integrated-verification-2026-09-05).

Use this model separately per backend/sensor tier:

```text
allocated GPU-hours = accepted flight-hours * raw allocated GPU-hours per raw flight-hour
                      / acceptance fraction
```

Budget CPU validation, storage and transfer separately. Measure startup, scene construction, reset, physics/PX4, capture, writer backpressure, encoding, finalization, validation, retries and idle allocation. Report median and tail costs by horizon, one/two workers per GPU, memory peaks and CPU limits. Count failed and timed-out attempts; measure complete persistent-worker lifetimes.

Illustrative scenario only: 0.787 with 80% acceptance gives 9,838 hours before omitted overhead, or about 11,313 with an assumed 15% overhead. Neither is a production quote. Dense modalities and new worlds require separate measurements.

Launch-fixed manifests contain about 1.65 GB for 1,943.46 simulated seconds, extrapolating to **30.6 TB retained for 10,000 hours** in the current format. At 80% acceptance, retaining all attempts would take approximately 38.2 TB before replicas, new sensors or extra training views. AP `/mnt/frtn` had approximately 787 GB free on 2026-09-05; provision storage before a 1,000-hour pilot.

Reproduce the historical scenario read-only:

```bash
python3 scripts/report_capacity.py /path/to/dataset --accepted-hours 10000 --acceptance 0.8 --overhead-fraction 0.15
```

Benchmark indexed image shards and chunked video against JPEG files using sequence throughput, random seek latency, decode CPU, quality, bytes per accepted hour and object count. Preserve capture timestamps independently of codecs. Avoid 360 million individually managed image objects. Full-coverage float32 depth at 640x360 and 10 Hz is about 332 TB before compression.

Maintain three tiers:

1. **Canonical archive:** sensor streams, PX4 logs, manifests and hashes.
2. **Training views:** compressed aligned sequences at selected rates.
3. **Regenerable labels:** bulky labels only when retained state/scene replay has been tested; seeds and version strings alone do not prove deterministic replay.

## Staged Execution

Each gate has an inspectable output:

1. **Correctness pilot:** honest navigation missions, independent predicates, live command evidence, explicit timing, interruption/retry tests and isolated worker resets. Rich inspection/search claims require visibility and coverage instrumentation.
2. **100 accepted hours:** persistent generation after reset qualification, bounded recording, storage and total cost measurements, and a small policy evaluated in closed loop on frozen world-family splits. Start with the reference backend and essential sensors.
3. **Backend comparison:** limited pinned Gazebo implementation and matched tasks; measure downstream benefit under equal generation and training budgets.
4. **1,000-hour diversity pilot:** expand independent worlds and composition based on policy failures. Provision storage before launch.
5. **3,000-hour checkpoint:** compare against the original frozen evaluation; add separately versioned challenges and X500 calibration as warranted.
6. **10,000-hour release:** generate toward coverage deficits and redirect saturated axes.

Compare learning curves by accepted hour, frame, visual/action token, mission family, simulator and storage byte. The percentages above are candidate coverage targets, not implemented capabilities.

## Immediate Engineering Decisions

[Engineering notes](engineering-notes.md) distinguish implemented foundations, verification evidence and remaining work. This plan defines the production gates.
