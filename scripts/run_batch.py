#!/usr/bin/env python3
"""Crash-safe single-GPU batch launcher; independent shards share POSIX locks."""
import fcntl
import ctypes
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with temp.open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def claim(path):
    f = path.open('a+')
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def published_ok(path, config_hash):
    try:
        receipt = json.loads((path / 'publication.json').read_text())
        return (receipt['config_hash'] == config_hash
                and receipt['validation_passed'] is True
                and receipt['manifest_sha256'] == digest(path / 'manifest.json'))
    except (OSError, ValueError, KeyError):
        return False


def publish(episode, destination, config_hash):
    if destination.exists():
        raise RuntimeError(f'Refusing to overwrite existing episode: {destination}')
    atomic_json(episode / 'publication.json', {
        'config_hash': config_hash, 'validation_passed': True,
        'manifest_sha256': digest(episode / 'manifest.json'),
        'published_at_unix': time.time(),
    })
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = libc.renameat2
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(episode), -100, os.fsencode(destination), 1) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), str(destination))
    fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fingerprint(repo, runtime, image_id, assets, config):
    names = subprocess.check_output(
        ['git', '-C', str(repo), 'ls-files', '-z', '--cached', '--others', '--exclude-standard']
    ).decode().split('\0')
    source = {name: digest(repo / name) for name in sorted(set(names))
              if name and (repo / name).is_file()}
    runtime_files = {}
    for root in (runtime / 'PegasusSimulator/extensions/pegasus.simulator',
                 runtime / 'isaac-python-deps'):
        for path in sorted(root.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                runtime_files[str(path.relative_to(runtime))] = digest(path)
    px4 = runtime / 'PX4-Autopilot'
    runtime_files['PX4-Autopilot/build/px4_sitl_default/bin/px4'] = digest(
        px4 / 'build/px4_sitl_default/bin/px4')
    for path in sorted((px4 / 'ROMFS').rglob('*')):
        if path.is_file():
            runtime_files[str(path.relative_to(runtime))] = digest(path)
    info = {'source': source, 'runtime': runtime_files, 'image': image_id,
            'asset_manifest': digest(assets / 'asset_manifest.json'), 'config': config}
    return hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest(), info


def main():
    preparation_started = time.monotonic()
    repo = Path(__file__).resolve().parent.parent
    runtime = Path(os.environ['RUNTIME_ROOT']).resolve()
    data = Path(os.environ['DATA_ROOT']).resolve()
    dataset_name = os.environ.get('DATASET_NAME', 'natural-valley-navigation-v1')
    if not dataset_name or Path(dataset_name).name != dataset_name or dataset_name in ('.', '..'):
        raise ValueError('DATASET_NAME must be a single directory name')
    dataset = data / 'datasets' / dataset_name
    assets = data / 'assets/polyhaven-v2'
    dataset.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    for name in ('.claims', '.attempts', '.workers'):
        (dataset / name).mkdir(exist_ok=True)
    fetch = [sys.executable, str(repo / 'simulation/fetch_assets.py'), '--output-root', str(assets)]
    with (assets / '.fetch.lock').open('a+') as asset_lock:
        fcntl.flock(asset_lock, fcntl.LOCK_EX)
        subprocess.run(fetch + (['--verify-only'] if (assets / 'asset_manifest.json').exists() else []), check=True)
    image = os.environ.get('ISAAC_IMAGE', 'nvcr.io/nvidia/isaac-sim:5.1.0')
    image_id = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
    network = os.environ.get('DOCKER_NETWORK_MODE', 'bridge')
    if network != 'bridge':
        raise ValueError('Batch workers require isolated bridge networking')
    start, end = int(os.environ.get('EPISODE_START', 0)), int(os.environ.get('EPISODE_END', 9))
    attempts = int(os.environ.get('MAX_ATTEMPTS', 3))
    timeout = float(os.environ.get('EPISODE_TIMEOUT_SECONDS', 7200))
    validation_timeout = float(os.environ.get('VALIDATION_TIMEOUT_SECONDS', 1800))
    group_size = int(os.environ.get('PERSISTENT_EPISODES_PER_WORKER', 1))
    worker_timeout = float(os.environ.get('PERSISTENT_WORKER_TIMEOUT_SECONDS', timeout * group_size))
    if not 1 <= group_size <= 8 or worker_timeout <= 0:
        raise ValueError('PERSISTENT_EPISODES_PER_WORKER must be 1..8 and worker timeout positive')
    if start < 0 or end < start or attempts < 1 or timeout <= 0 or validation_timeout <= 0:
        raise ValueError('Invalid episode range, attempts, or timeout')
    config = {'seed_base': int(os.environ.get('SEED_BASE', 5200)), 'scene_version': 'v2',
              'generator_threads': int(os.environ.get('ISAAC_CPU_THREADS', 24)),
              'persistent_episodes_per_worker': group_size}
    base_hash, provenance = fingerprint(repo, runtime, image_id, assets, config)
    atomic_json(dataset / f'configuration-{base_hash}.json', provenance)
    preparation_wall_s = time.monotonic() - preparation_started
    atomic_json(dataset / ('batch-' + uuid.uuid4().hex + '.json'), {
        'preparation_wall_s': preparation_wall_s, 'config_fingerprint': base_hash,
        'episode_start': start, 'episode_end': end, 'started_at_unix': time.time() - preparation_wall_s,
    })
    active = set()

    def cleanup(signum=None, frame=None):
        for name in list(active):
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if signum is not None:
            raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    last_run_times = {}

    def run_container(args, logfile, gpu=False, limit=timeout, ownership_roots=None):
        name = 'vln-' + uuid.uuid4().hex
        command = ['docker', 'run', '--rm', '--name', name, '--user', 'root', '--network=bridge']
        if gpu:
            command += ['--gpus', 'device=' + os.environ.get('GPU_DEVICE', '0')]
        command += ['-e', 'ACCEPT_EULA=Y', '-e', 'PRIVACY_CONSENT=Y',
                    '-e', 'PYTHONPATH=/runtime/isaac-python-deps:/runtime/PegasusSimulator/extensions/pegasus.simulator',
                    '-e', 'OMP_NUM_THREADS=' + str(config['generator_threads']),
                    '-v', f'{repo}:/workspace/repo:ro', '-v', f'{runtime}:/runtime',
                    '-v', f'{data}:/data',
                    '-v', f'{data}/isaac-cache/ov:/root/.cache/ov',
                    '-v', f'{data}/isaac-cache/glcache:/root/.cache/nvidia/GLCache',
                    '-v', f'{data}/isaac-cache/computecache:/root/.nv/ComputeCache',
                    '--entrypoint', '/isaac-sim/python.sh', image_id] + args
        active.add(name)
        container_started = time.monotonic()
        try:
            with logfile.open('xb') as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=limit)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        finally:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            active.discard(name)
            last_run_times['container_wall_s'] = time.monotonic() - container_started
            # SimulationApp may terminate Python without unwinding finally blocks.
            # Repair ownership outside that process, with only this attempt mounted.
            roots = [Path(p).resolve() for p in (ownership_roots or [logfile.parent])]
            for ownership_root in roots:
                relative = ownership_root.relative_to(dataset.resolve())
                if relative.parts[0] not in ('.attempts', '.workers') or len(relative.parts) < 2:
                    raise ValueError('Ownership repair must target a private attempt or worker directory')
            repair_name = 'vln-' + uuid.uuid4().hex
            active.add(repair_name)
            ownership_started = time.monotonic()
            try:
                mounts = []
                for i, ownership_root in enumerate(roots):
                    mounts += ['-v', f'{ownership_root}:/output/{i}']
                subprocess.run([
                    'docker', 'run', '--rm', '--name', repair_name, '--network=none', '--user', 'root',
                ] + mounts + ['--entrypoint', '/usr/bin/chown', image_id,
                    '-R', '-P', '--no-dereference', f'{os.getuid()}:{os.getgid()}', '/output',
                ], check=True, timeout=120, stdout=subprocess.DEVNULL)
            finally:
                subprocess.run(['docker', 'rm', '-f', repair_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                active.discard(repair_name)
                last_run_times['ownership_wall_s'] = time.monotonic() - ownership_started

    def container_path(path):
        return '/data/' + str(path.relative_to(data))

    def pending_episode(episode_id):
        episode_name = f'episode-{episode_id:03d}'
        config_hash = hashlib.sha256(f'{base_hash}:{episode_id}'.encode()).hexdigest()
        destination = dataset / episode_name
        if published_ok(destination, config_hash):
            audit = dataset / '.attempts' / episode_name / ('resume-' + uuid.uuid4().hex)
            audit.mkdir(parents=True)
            if run_container([
                    '/workspace/repo/simulation/validate_dataset.py', '--episode', container_path(destination),
                    '--output', container_path(audit / 'validation.json'), '--require-success'],
                    audit / 'validator.log', limit=validation_timeout):
                print(f'{episode_name}: matching publication revalidated', flush=True)
                return None
            raise RuntimeError(f'{destination}: published data failed revalidation; preserve it and use a new DATASET_NAME')
        if destination.exists():
            raise RuntimeError(f'{destination} exists without matching validated configuration; select a new DATASET_NAME')
        return {'episode_id': episode_id, 'name': episode_name, 'config_hash': config_hash,
                'destination': destination}

    def create_attempt(item):
        attempt_root = dataset / '.attempts' / item['name'] / uuid.uuid4().hex
        attempt_root.mkdir(parents=True)
        private = attempt_root / item['name']
        status = {'episode_id': item['episode_id'], 'config_hash': item['config_hash'],
                  'started_at_unix': time.time()}
        atomic_json(attempt_root / 'attempt.json', status)
        return {'item': item, 'root': attempt_root, 'private': private, 'status': status,
                'started': time.monotonic()}

    def validate_publish(attempt, worker_exit_ok):
        item, private, attempt_root, status = (attempt[k] for k in ('item', 'private', 'root', 'status'))
        # A later episode failure must not discard an earlier complete episode.
        generated = (private / 'manifest.json').is_file()
        validated = False
        validation_started = time.monotonic()
        if generated:
            validated = run_container([
                '/workspace/repo/simulation/validate_dataset.py', '--episode', container_path(private),
                '--output', container_path(attempt_root / 'validation.json'), '--require-success'],
                attempt_root / 'validator.log', limit=validation_timeout)
        status.update(generated=generated, worker_exit_ok=worker_exit_ok, validated=validated,
                      validation_wall_s=time.monotonic() - validation_started if generated else 0,
                      total_wall_seconds=time.monotonic() - attempt['started'], ended_at_unix=time.time(),
                      output_bytes=sum(p.stat().st_size for p in private.rglob('*') if p.is_file()) if private.exists() else 0)
        atomic_json(attempt_root / 'attempt.json', status)
        if validated:
            publish(private, item['destination'], item['config_hash'])
        return validated

    def generate_group(items, persistent):
        group = [create_attempt(item) for item in items]
        common = ['/workspace/repo/simulation/generate_episode.py', '--scene-version', 'v2',
                  '--assets-root', '/data/assets/polyhaven-v2', '--px4-dir', '/runtime/PX4-Autopilot']
        worker_id = uuid.uuid4().hex
        worker_root = dataset / '.workers' / worker_id
        worker_root.mkdir()
        plan = [{'episode_id': a['item']['episode_id'], 'seed': config['seed_base'] + a['item']['episode_id'],
                 'attempt_dir': container_path(a['private']), 'config_hash': a['item']['config_hash']}
                for a in group]
        atomic_json(worker_root / 'plan.json', plan)
        ledger = {'worker_id': worker_id, 'started_at_unix': time.time(), 'persistent': persistent,
                  'attempts': [str(a['root'].relative_to(dataset)) for a in group],
                  'allocation_policy': 'equal shares across started episode directories; if none started, all planned episodes; last share carries floating-point remainder'}
        atomic_json(worker_root / 'worker.json', ledger)
        for a in group:
            a['status']['worker_id'] = worker_id
            atomic_json(a['root'] / 'attempt.json', a['status'])
        print(f'worker {worker_id}: episodes {[item["episode_id"] for item in items]}, persistent={persistent}', flush=True)
        if persistent:
            args = common + ['--episode-plan', container_path(worker_root / 'plan.json')]
        else:
            one = plan[0]
            args = common + ['--attempt-dir', one['attempt_dir'], '--config-hash', one['config_hash'],
                             '--episode-id', str(one['episode_id']), '--seed', str(one['seed'])]
        exit_ok = run_container(args, worker_root / 'generator.log', gpu=True,
                                limit=worker_timeout if persistent else timeout,
                                ownership_roots=[worker_root] + [a['root'] for a in group])
        total = last_run_times['container_wall_s']
        ownership_time = last_run_times['ownership_wall_s']
        started = [a for a in group if a['private'].exists()]
        charged = started or group
        shares = []
        for i, a in enumerate(charged):
            shares.append(total / len(charged) if i < len(charged) - 1 else total - sum(shares))
        allocations = {a['root']: share for a, share in zip(charged, shares)}
        ledger.update(ended_at_unix=time.time(), allocated_gpu_wall_s=total, worker_exit_ok=exit_ok,
                      ownership_repair_wall_s=ownership_time,
                      allocations={str(path.relative_to(dataset)): share for path, share in allocations.items()})
        atomic_json(worker_root / 'worker.json', ledger)
        for a in group:
            share = allocations.get(a['root'], 0.0)
            a['status'].update(allocated_gpu_wall_s=share, generation_wall_seconds=share,
                               generator_started=a in started, allocation_policy=ledger['allocation_policy'])
            atomic_json(a['root'] / 'attempt.json', a['status'])
        return [a['item'] for a in group if not validate_publish(a, exit_ok)]

    failed = []
    busy = []
    try:
        for chunk_start in range(start, end + 1, group_size):
            # All cohort claims remain held through publication and individual retries.
            with ExitStack() as claims:
                pending = []
                for episode_id in range(chunk_start, min(end + 1, chunk_start + group_size)):
                    episode_name = f'episode-{episode_id:03d}'
                    lock = claim(dataset / '.claims' / (episode_name + '.lock'))
                    if lock is None:
                        busy.append(episode_id)
                        print(f'{episode_name}: claimed by another worker', flush=True)
                        continue
                    claims.enter_context(lock)
                    item = pending_episode(episode_id)
                    if item is not None:
                        pending.append(item)
                if not pending:
                    continue
                remaining = generate_group(pending, persistent=group_size > 1 and len(pending) > 1)
                for item in remaining:
                    for retry in range(1, attempts):
                        if not generate_group([item], persistent=False):
                            break
                    else:
                        failed.append(item['episode_id'])
    finally:
        cleanup()
    print(json.dumps({'failed': failed, 'claimed_elsewhere': busy, 'dataset': str(dataset)}), flush=True)
    return 3 if failed else 4 if busy else 0


if __name__ == '__main__':
    raise SystemExit(main())
