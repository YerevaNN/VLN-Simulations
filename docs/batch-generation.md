# Batch generation and recovery

`scripts/run_batch.sh` delegates to the CPU-side `scripts/run_batch.py`. Export the settings in `configs/example.env` before launching. Independent GPU shards can use the same dataset name with disjoint episode ranges. Overlapping ranges are protected by nonblocking POSIX file locks; a worker that encounters another claim reports the episode and exits with code 4 so the cohort can be checked or retried later.

Each episode gets a private `.attempts/episode-N/<uuid>/episode-N` directory. Successful generation is followed by explicit single-episode validation with `--require-success`; only a validated attempt is atomically renamed to the published `episode-N`. Failed attempts and their logs remain intact. The batch never deletes or replaces a published episode. `SIGINT`, `SIGTERM`, and wall-clock timeouts remove only the worker's UUID-named Docker container; PX4 exits with that container. Abrupt host or launcher termination can leave containers behind: identify them by their `vln-<uuid>` name and the corresponding Docker command before stopping them. Advisory claims are released when the owning process dies.

Resume requires a matching configuration fingerprint and publication receipt, then reruns validation against the published payload. A changed or untrusted publication stops the run and requires a new dataset name; historical status-only manifests are deliberately insufficient. Fingerprints cover source files including dirty/untracked nonignored files, the asset lockfile and manifest, Pegasus and Python dependency files, PX4 binary and ROMFS, the resolved Docker image ID, seed settings, and thread settings. Asset verification is serialized across shards. Keep source/runtime files stable during a cohort; changing them while workers run invalidates reproducibility.

The launcher no longer validates an entire shared directory while other shards may be writing. After the cohort completes, aggregate only its explicit published episode paths with repeated validator `--episode` arguments. Supply `--expected` only for that completed cohort. Dataset-wide validation is suitable when no writer is active and the intended cohort is the entire dataset.

## Capacity evidence

`batch-<uuid>.json` records preparation wall time. Every private attempt has `attempt.json`, and (when run) validator logs and `validation.json`. Generator logs, immutable input plans, and allocation ledgers live under `.workers/<uuid>/`. Attempt records include timestamps, allocated GPU wall seconds, validation wall seconds, total wall seconds, output bytes, and generation/validation outcomes. The GPU timer includes Docker startup and cleanup; CPU-only validation and output ownership repair are separate. Failed and rejected attempts remain part of the cost. Preparation is shared across the batch and must not be counted once per episode.

The worker ledger records the full allocation once. Per-attempt allocation divides that total equally across episode directories the generator started; if it failed before creating any directory, all planned episodes share startup cost. The final share carries the floating-point remainder, so shares sum to the exact worker total. Planned but unstarted episodes receive zero when another episode did start. This is a cost attribution policy, not a measurement of each episode's own computation. Capacity reports sum attempt shares, check them against worker ledgers, and never add the worker total again. Missing or inconsistent records suppress complete-cost projections.

## Persistent application experiment

The batch default is a fresh container per attempt with 24 CPU threads, configurable through ISAAC_CPU_THREADS. An independent 180-second native reset deadline emits a diagnostic stack before terminating a stalled initializer; the outer worker watchdog still owns container cleanup. Set `PERSISTENT_EPISODES_PER_WORKER=2` to opt into experimental application reuse; values are bounded to 1–8. The launcher holds every cohort claim, creates private attempts and an immutable plan, and applies a whole-worker watchdog (`PERSISTENT_WORKER_TIMEOUT_SECONDS`, default episode timeout multiplied by configured cohort size). Each episode constructs a fresh world and PX4 instance; this does not claim cached-scene reuse. Completed outputs are independently validated and published even if a later episode crashes. Invalid and unfinished members retain their artifacts and retry individually within `MAX_ATTEMPTS`.

Capped reset checks establish only basic reuse behavior. Before increasing a production cohort, compare full episodes with the same seeds against fresh processes, inspect PX4/camera reset evidence, and monitor GPU/host memory across repeated episodes. Keep the default until these checks support the intended workload.

The generator also accepts `--episode-plan /path/plan.json` directly for diagnostics. A plan is a JSON list:

```json
[
  {"episode_id": 0, "seed": 5200, "attempt_dir": "/data/experiments/reset-check/run-unique/episode-000", "config_hash": "experiment-fingerprint", "max_sim_seconds": 10},
  {"episode_id": 1, "seed": 5201, "attempt_dir": "/data/experiments/reset-check/run-unique/episode-001", "config_hash": "experiment-fingerprint", "max_sim_seconds": 10}
]
```

Run the ordinary generator invocation inside the Isaac container, adding `--episode-plan /data/experiments/reset-check/plan.json` and retaining its assets/runtime arguments. Paths in the plan are container paths; every attempt directory must be fresh. The example's short duration is a reset diagnostic and cannot supply successful expert episodes. Direct generator invocation does not provide the launcher's claims, watchdog, or publication gate; keep those diagnostic outputs outside published datasets.

## Remaining limits

Claims require a shared filesystem with working POSIX `flock` and atomic directory rename; do not substitute an object-store mount without checking those semantics. There is no automatic orphan-container reaper or rejected-attempt retention policy. Shared shader caches and concurrent workers need throughput benchmarks. Full runtime hashing adds preparation cost but avoids silently treating a changed local installation as the same dataset configuration.
