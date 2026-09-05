#!/usr/bin/env python3
"""Read-only capacity model; historical partial timers never become allocated GPU time."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def attempt_metrics(root, published, target_hours):
    """Sum attempts once; publication moves payloads but never copies their metrics."""
    warnings = []
    accepted = {}
    for path, manifest in published:
        try:
            receipt = json.loads((path.parent / 'publication.json').read_text())
            valid = (receipt.get('validation_passed') is True and manifest.get('status') == 'success'
                     and receipt.get('config_hash') == manifest.get('config_hash')
                     and receipt.get('manifest_sha256') == hashlib.sha256(path.read_bytes()).hexdigest())
            if valid:
                accepted[(path.parent.name, receipt['config_hash'])] = manifest
            else:
                warnings.append(f'{path.parent.name}: invalid publication receipt; excluded from accepted hours')
        except (OSError, ValueError, KeyError):
            warnings.append(f'{path.parent.name}: no verifiable publication receipt; excluded from accepted hours')
    paths = sorted(root.glob('.attempts/episode-*/*/attempt.json'))
    if not paths:
        return None
    records = []
    for path in paths:
        try:
            record = json.loads(path.read_text())
            if not isinstance(record, dict):
                raise ValueError('attempt metrics must be an object')
            records.append((path, record))
        except (OSError, ValueError):
            warnings.append(f'{path.relative_to(root)}: unreadable attempt metrics')
    gpu_s = validation_s = bytes_recorded = 0
    gpu_count = validation_count = completed_count = 0
    raw_duration = sum(float(m.get('duration_s', 0)) for _, m in published)
    private_manifests = list(root.glob('.attempts/episode-*/*/episode-*/manifest.json'))
    for path in private_manifests:
        try:
            raw_duration += max(0, float(json.loads(path.read_text()).get('duration_s', 0)))
        except (OSError, ValueError, TypeError):
            warnings.append(f'{path.relative_to(root)}: unreadable raw duration')
    matching_accepted = set()
    for path, record in records:
        def numeric(key):
            value = record.get(key)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None
        gpu = numeric('allocated_gpu_wall_s')
        validation = numeric('validation_wall_s')
        if gpu is not None:
            gpu_s += gpu
            gpu_count += 1
        else:
            warnings.append(f'{path.relative_to(root)}: missing GPU allocation timing (possibly interrupted)')
        if validation is not None:
            validation_s += validation
            validation_count += 1
        else:
            warnings.append(f'{path.relative_to(root)}: missing CPU validation timing')
        size = numeric('output_bytes')
        if size is not None:
            bytes_recorded += size
        if numeric('ended_at_unix') is not None:
            completed_count += 1
        key = (path.parent.parent.name, record.get('config_hash'))
        if record.get('validated') is True and key in accepted:
            matching_accepted.add(key)
    for key in accepted.keys() - matching_accepted:
        warnings.append(f'{key[0]}: accepted publication has no matching completed attempt metrics')
    orphan_attempts = [p for p in root.glob('.attempts/episode-*/*')
                       if p.is_dir() and not p.name.startswith('resume-') and not (p / 'attempt.json').exists()]
    if orphan_attempts:
        warnings.append(f'{len(orphan_attempts)} attempt directories lack metrics; allocation is incomplete')
    preparation_s = 0
    prep_count = 0
    for path in root.glob('batch-*.json'):
        try:
            value = json.loads(path.read_text())['preparation_wall_s']
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('invalid preparation time')
            preparation_s += value
            prep_count += 1
        except (OSError, ValueError, KeyError, TypeError):
            warnings.append(f'{path.name}: missing preparation timing')
    if not prep_count:
        warnings.append('No batch preparation metrics; preparation CPU time is unknown')
    accepted_h = sum(float(m.get('duration_s', 0)) for m in accepted.values()) / 3600
    ownership_s = 0.0
    worker_coverage_ok = True
    for path in root.glob('.workers/*/worker.json'):
        try:
            worker = json.loads(path.read_text())
            ownership_s += float(worker.get('ownership_repair_wall_s', 0))
            total = float(worker['allocated_gpu_wall_s'])
            allocated = worker['allocations']
            if not math.isclose(sum(allocated.values()), total, abs_tol=1e-9):
                raise ValueError('worker allocation shares differ from total')
            for attempt_path, share in allocated.items():
                attempt = json.loads((root / attempt_path / 'attempt.json').read_text())
                if attempt.get('worker_id') != worker['worker_id'] or not math.isclose(attempt['allocated_gpu_wall_s'], share, abs_tol=1e-9):
                    raise ValueError('worker ledger differs from attempt allocation')
        except (OSError, ValueError, TypeError, KeyError):
            worker_coverage_ok = False
            warnings.append(f'{path.relative_to(root)}: incomplete or inconsistent worker allocation ledger')
    for _, record in records:
        if not record.get('worker_id'):
            value = record.get('ownership_repair_wall_s', 0)
            if isinstance(value, (float, int)) and math.isfinite(value) and value >= 0:
                ownership_s += value
    gpu_complete = (worker_coverage_ok and gpu_count == len(paths) and completed_count == len(paths) and not orphan_attempts
                    and len(matching_accepted) == len(accepted)
                    and len(accepted) == len(published))
    if len(private_manifests) + len(matching_accepted) < len(paths):
        warnings.append('Some attempts lack final manifests; raw flight hours are a recorded lower bound')
    partial_ratio = gpu_s / 3600 / accepted_h if accepted_h > 0 else None
    ratio = partial_ratio if gpu_complete else None
    return {
        'attempts': len(paths), 'completed_attempts': completed_count,
        'accepted_published_episodes': len(accepted), 'accepted_published_flight_hours': accepted_h,
        'recorded_raw_flight_hours': raw_duration / 3600,
        'attempts_with_gpu_timing': gpu_count, 'gpu_timing_complete': gpu_complete,
        'recorded_allocated_gpu_hours': gpu_s / 3600,
        'recorded_gpu_hours_per_accepted_hour_lower_bound': partial_ratio,
        'allocated_gpu_hours_per_accepted_hour': ratio,
        'projected_allocated_gpu_hours_at_observed_yield': ratio * target_hours if ratio is not None else None,
        'recorded_cpu_validation_hours': validation_s / 3600,
        'recorded_cpu_ownership_repair_hours': ownership_s / 3600,
        'attempts_with_validation_timing': validation_count,
        'recorded_preparation_wall_hours': preparation_s / 3600,
        'batches_with_preparation_timing': prep_count,
        'recorded_attempt_output_bytes': int(bytes_recorded),
        'warnings': warnings,
        'scope': 'Observed attempt allocations include retries and rejects. Projection assumes the same workload and observed yield; do not apply the scenario acceptance factor again. CPU validation and batch preparation are separate, and summed wall time is not elapsed cohort time or hardware utilization. Resume revalidation CPU time is not currently recorded.',
    }


def capacity_report(root, accepted_hours=10000.0, acceptance=0.8, overhead_fraction=0.15):
    if accepted_hours <= 0 or not 0 < acceptance <= 1 or overhead_fraction < 0:
        raise ValueError("hours must be positive, acceptance in (0,1], overhead nonnegative")
    root = Path(root)
    published = [(path, json.loads(path.read_text())) for path in sorted(root.glob("episode-*/manifest.json"))]
    manifests = [manifest for _, manifest in published]
    observed = attempt_metrics(root, published, accepted_hours)
    if not manifests and observed is None:
        raise ValueError("No published episode manifests or attempt metrics")
    duration = sum(float(m.get("duration_s", 0)) for m in manifests)
    if duration <= 0 and observed is None:
        raise ValueError("No positive recorded duration")
    recorded_wall = sum(float(m.get("wall_time_s", 0)) for m in manifests)
    size = sum(sum(int(f["bytes"]) for f in m.get("files", {}).values()) for m in manifests)
    ratio = recorded_wall / duration if duration > 0 else None
    baseline = accepted_hours * ratio / acceptance if ratio is not None else None
    return {
        "schema_version": "uav-capacity-report-v2",
        "primary_measurement": "observed_attempt_allocations" if observed is not None else "legacy_partial_timer_scenario",
        "observed_attempt_allocations": observed,
        "dataset": str(Path(root).resolve()),
        "episodes": len(manifests),
        "recorded_flight_hours": duration / 3600,
        "recorded_wall_hours": recorded_wall / 3600,
        "recorded_wall_hours_per_flight_hour": ratio,
        "recorded_bytes": size,
        "historical_timer_warning": "wall_time_s is a legacy partial generation timer; excludes application startup, scene construction, hashing and external validation. It is NOT measured GPU utilization or complete allocated GPU time.",
        "scenario": {
            "target_accepted_hours": accepted_hours,
            "assumed_acceptance_fraction": acceptance,
            "assumed_additional_overhead_fraction": overhead_fraction,
            "raw_hours_required": accepted_hours / acceptance,
            "partial_timer_projected_hours_before_overhead": baseline,
            "partial_timer_projected_hours_with_assumed_overhead": baseline * (1 + overhead_fraction) if baseline is not None else None,
            "retained_dataset_TB_at_current_format": size / duration * accepted_hours * 3600 / 1e12 if duration > 0 else None,
            "raw_dataset_TB_if_all_attempts_retained": size / duration * accepted_hours * 3600 / acceptance / 1e12 if duration > 0 else None,
            "scope": "Scenario using observed format and partial timers, not a production quote; excludes training, replicas, new sensors, and backend differences."
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--accepted-hours", type=float, default=10000)
    parser.add_argument("--acceptance", type=float, default=0.8)
    parser.add_argument("--overhead-fraction", type=float, default=0.15)
    args = parser.parse_args()
    print(json.dumps(capacity_report(args.dataset_root, args.accepted_hours, args.acceptance, args.overhead_fraction), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
