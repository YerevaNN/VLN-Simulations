# Engineering review and implementation notes

Reviewed on 2026-09-05 against the AP working tree at `/auto/home/hrant/VLN-Simulations`, starting from `4c0c3a7` plus existing uncommitted horizon/launch/viewer edits. This is the shared handoff for decisions and open challenges. The [scale plan](scale-plan.md) defines staged investment and evaluation gates.

## Commands cause the flight

The expert operates online. Each cycle reads current privileged simulator state, computes joystick axes, sends MAVLink `MANUAL_CONTROL` to PX4 and records the command. PX4 stabilization and simulated vehicle dynamics produce subsequent motion. Actions are not reconstructed from completed trajectories.

The expert is privileged and scripted: it knows the route and exact state. It is not a learned vision-language policy. Its actions can supervise one, but training inputs must separate deployable observations from privileged labels. UDP transmission alone is not application acknowledgement. ULog matching independently confirmed all 1,101 distinct received control samples in the accepted 238.06-second qualification flight and actual armed Position mode. Exact application latency still needs clock alignment.

Original exports paired an assigned frame simulation time with its nearest action. This did not distinguish capture, availability, decision and application time or define what a 2 Hz policy does between predictions. Preserve these clocks and future command chunks/durations; one sampled 50 Hz stick value does not describe a 500 ms interval.

## Mission semantics

The old first route instructed flight beneath a bridge while commanding an altitude about 21 m above the deck. Other instructions claimed branch mapping or target-facing inspection without matching geometry or camera objectives. Waypoint progress alone cannot validate those tasks.

The corrective scope is honest navigation with scene-bound targets and independent progress/landing predicates. Do not restore inspection, photogrammetry, visual search completion or target-in-view language merely because a route passes nearby. Those tasks need executable visibility, occlusion, dwell, face or area coverage and corresponding control. A gimbal or target-facing yaw objective is a likely next step.

Worlds currently use an explicitly labeled route-cleared legacy distribution. Production should sample worlds first and plan feasible routes afterward. Removing clearance without a planner would introduce uncontrolled failures. World ancestry and split assignment must be distinct from episode/scatter seeds.

## Engineering foundations

Implemented foundations include immutable validated attempts and stable configuration identity; bounded asynchronous image writing and streamed tables; capture/availability/transmission clocks and future command chunks; independent PX4, mission and contact validation; authored scene inventories and ancestry-based splits; paginated playback and indexed archive export. Validity and successful task completion remain separate labels.

See [batch generation and recovery](batch-generation.md) for claims, attempts, publication, watchdogs and persistent execution. Assets are pinned by the repository [lockfile](../configs/assets.lock.json): 89 exact files across 18 assets. The downloader uses pinned URLs and SHA-256 without the mutable catalog. `--verify-only` checks local bytes offline; failed downloads do not replace existing files.

## Performance qualification

Persistent execution must reset PX4, sockets, sensor counters, clocks, world and expert state. Qualify consecutive episodes, compare fresh execution, monitor memory and inject failures. Bound worker lifetime and keep a fresh-process fallback. Reuse must not silently substitute a world for a different seed/revision.

A bounded writer queue must copy image buffers, propagate errors and expose backpressure. Never trade timing correctness for unbounded buffering or silently dropped frames. Stream tables and separate postprocessing from active simulation where practical.

Temporal joins now use binary search instead of scanning every action for each frame. A CPU microbenchmark produced 91,800 training rows across 2/5/10 Hz views from 270,000 actions and 54,000 frames in 0.478 seconds, excluding JSON serialization and disk writes. This is not an end-to-end speedup.

Disable unused headless viewport updates; compare worker/thread counts by accepted flight-hours per allocated GPU-hour. The [Isaac 5.1 handbook](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/reference_material/sim_performance_optimization_handbook.html) documents those controls. Scene partitioning and collision simplification require visual/contact checks.

## Integrated verification (2026-09-05)

- **CPU and viewer:** 61 CPU tests and four viewer API tests pass, together with Node asynchronous-viewer checks, Python compilation, shell syntax and whitespace checks. Interactive playback was checked by seeking and switching episodes in a temporary viewer; the existing hosted viewer was not redeployed.
- **Complete pipeline:** engineering-threads24-20260905-1788611884/episode-000 passed generate → independently validate → atomically publish, with clean generator and launcher exits. It recorded 238.06 seconds and 2,334 camera frames. All 19 waypoints, a 6.980-radian directed orbit, above-bridge crossing and stable terminal landing passed. PX4 detected landing and accepted normal disarming.
- **Contact evidence:** independent validation found 3,301 allowed physical ground contacts, 65,979 proximity reports and zero physical collisions, with full recorded monitoring coverage of collidable geometry. Earlier attempts rejected by the initial predictive-contact classifier remain intact; they were not relabeled or republished.
- **Recovery:** an identical batch revalidated the publication in 7.53 seconds with the worker count unchanged at one. A real rejected landing attempt hit the 900-second watchdog; its container was removed and artifacts/cost retained. The capacity report counts approximately 0.251 allocated GPU-hours and correctly declines an accepted-hour projection when no episode was accepted. Fixture tests cover overlapping claims, no-overwrite publication, resume and partial persistent-worker recovery.
- **Reuse:** two capped 15-second episodes ran consecutively in one application with fresh world/PX4/sensors and matching initial states. This establishes basic reset behavior only; full-episode parity and long-running memory stability remain unqualified.

The archive roundtrip also passed: all 2,350 members (218,517,681 bytes) were read through indexes from six test shards and matched the published source bytes exactly. The accepted attempt recorded 423.08 allocated GPU seconds for 238.06 flight seconds (1.777 GPU-hours per accepted hour for this short case), plus 6.92 seconds of CPU validation. This excludes separate engineering-debug datasets and is not a production throughput or acceptance-rate estimate.

Two eight-thread runs stalled in native physics initialization at SimulationContext.play/world.reset. A 24-thread run completed reset in 49.3 seconds and passed the full pipeline; defaults and example settings now use 24, configurable per host. This comparison does not prove the native root cause. A 180-second kernel reset deadline, diagnostic phase logs and a delayed stack dump now bound such failures; the total worker watchdog remains. Qualify thread counts and repeated resets for each production workload.

Exact resume was verified before final documentation/example edits; fingerprints intentionally cover the working source snapshot, so subsequent source changes require a new dataset configuration.

Runtime artifacts and logs remain under /mnt/frtn/uav-sim/quality-20260905 and the corresponding engineering-* datasets on AP. These are diagnostic datasets, not a production release.

### Runtime defects discovered and corrected

Historical episodes disarmed above ground and dropped, reaching about 4.3 m/s in the terminal second. The controller now descends gently, requires sustained physical ground contact and low speed, then holds bottom stick until PX4 permits normal disarming. This satisfies PX4's commanded-descent landing detector without forced disarming or relaxed success thresholds.

PhysX can report contacts before surfaces touch. Positive-separation, zero-impulse manifolds remain proximity evidence; physical contact requires at least one point and either applied impulse or nonpositive separation. The same rule gates touchdown and independent collision evaluation. See [PhysX contact-distance semantics](https://nvidia-omniverse.github.io/PhysX/physx/5.1.2/docs/AdvancedCollisionDetection.html). Coverage is limited to geometry with collision shapes; imported visual-only meshes are not certified collision-free. Contact/rest offsets and vehicle collision extent still need calibration.

Isaac teardown invalidated imported numerical state and triggered a native garbage-collection crash. Numerical episode evaluation now precedes teardown, while a clean CPU subprocess performs exports and hashing. The isolated worker explicitly closes resources, flushes output and preserves its actual outcome through controlled process exit. The accepted full run verified clean shutdown and finalization with this workaround; requalify it when upgrading Isaac.

## Remaining production challenges

- **Perception tasks:** target-facing control, visibility/occlusion and coverage evidence; language from verified predicates.
- **Contacts and clearance:** calibrated vehicle extent, imported-asset collision proxies, continuous near-miss/contact evidence and terrain-relative altitude. Route proximity is not a full safety certificate.
- **Timing and sensors:** PX4 clock calibration, raw onboard sensors, simulated delivery latency/failures and fresh-frame identity.
- **Worlds and splits:** independent generation/planning, ancestry-based partitions frozen before training and held-out family/composition evaluation.
- **Storage:** sharded image/video decode and seek benchmarks, capacity provisioning, rejected metadata and representative rejected-data retention.
- **Backend value:** a small pinned Gazebo comparison after reference-pipeline correctness; select mixture through downstream results.
- **Real calibration:** dynamics, camera and operator statistics, with a fixed real evaluation.

The next research milestone is correctness followed by 100 accepted hours and a measured closed-loop policy result. The 10K-hour plan is a staged research proposal, not a generation run launched by these engineering changes.
