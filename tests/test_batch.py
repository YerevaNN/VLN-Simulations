"""CPU-only safety checks: publication, process claims, and launcher failures."""
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import sys

spec = importlib.util.spec_from_file_location('batch', Path(__file__).parents[1] / 'scripts/run_batch.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def try_claim(path, q):
    handle = batch.claim(Path(path))
    q.put(handle is not None)
    if handle:
        handle.close()


class BatchSafety(unittest.TestCase):
    def test_direct_script_imports_sibling_and_preserves_script_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / 'scripts'; scripts.mkdir()
            (scripts / 'sibling.py').write_text('VALUE = 37\n')
            script = scripts / 'main.py'
            script.write_text('from sibling import VALUE\nimport json,sys\nprint(json.dumps([VALUE,sys.argv]))\n')
            result = subprocess.run([sys.executable, str(script), '--flag', 'value'],
                                    cwd=root, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), [37, [str(script), '--flag', 'value']])

    def test_claim_is_exclusive_and_recovers_on_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'claim'
            lock = batch.claim(path)
            ctx = multiprocessing.get_context('spawn')
            q = ctx.Queue()
            p = ctx.Process(target=try_claim, args=(str(path), q))
            p.start()
            self.assertFalse(q.get(timeout=10))
            p.join(10)
            self.assertEqual(p.exitcode, 0)
            lock.close()
            p = ctx.Process(target=try_claim, args=(str(path), q))
            p.start()
            self.assertTrue(q.get(timeout=10))
            p.join(10)
            self.assertEqual(p.exitcode, 0)

    def test_publication_is_immutable_and_fingerprinted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attempt = root / 'attempt'
            attempt.mkdir()
            (attempt / 'manifest.json').write_text('{"status":"success"}')
            final = root / 'episode-000'
            batch.publish(attempt, final, 'config-A')
            self.assertFalse(attempt.exists())
            self.assertTrue(batch.published_ok(final, 'config-A'))
            self.assertFalse(batch.published_ok(final, 'config-B'))
            other = root / 'other'
            other.mkdir()
            with self.assertRaises(RuntimeError):
                batch.publish(other, final, 'config-A')
            self.assertTrue(other.exists())
            (final / 'manifest.json').write_text('{}')
            self.assertFalse(batch.published_ok(final, 'config-A'))

    def test_unpublished_success_is_not_resumable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'manifest.json').write_text('{"status":"success"}')
            self.assertFalse(batch.published_ok(path, 'config-A'))

    def test_publication_cannot_replace_racing_empty_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'; source.mkdir()
            (source / 'manifest.json').write_text('{}')
            destination = Path(tmp) / 'destination'
            write = batch.atomic_json
            def race(path, value):
                write(path, value)
                destination.mkdir()
            with patch.object(batch, 'atomic_json', side_effect=race):
                with self.assertRaises(FileExistsError):
                    batch.publish(source, destination, 'config')
            self.assertTrue(source.exists())
            self.assertEqual(list(destination.iterdir()), [])

    def test_launcher_timeout_retry_publication_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            count = {'generation': 0, 'validation': 0, 'cleanup': 0, 'ownership': 0}

            def fake_run(command, **kwargs):
                if command[:3] == ['docker', 'rm', '-f']:
                    count['cleanup'] += 1
                elif command[:2] == ['docker', 'run']:
                    if '/usr/bin/chown' in command:
                        count['ownership'] += 1
                        self.assertIn('--network=none', command)
                        self.assertIn('--no-dereference', command)
                        return subprocess.CompletedProcess(command, 0)
                    image_position = command.index('sha256:image')
                    self.assertTrue(command[image_position + 1].startswith('/workspace/repo/simulation/'))
                    self.assertNotIn('-c', command)
                    if '--attempt-dir' in command:
                        count['generation'] += 1
                        private = root / command[command.index('--attempt-dir') + 1].removeprefix('/data/')
                        private.mkdir()
                        if count['generation'] == 1:
                            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
                        (private / 'manifest.json').write_text('{"status":"success"}')
                    else:
                        count['validation'] += 1
                return subprocess.CompletedProcess(command, 0)

            env = {'RUNTIME_ROOT': tmp, 'DATA_ROOT': tmp, 'DATASET_NAME': 'test',
                   'EPISODE_START': '0', 'EPISODE_END': '0', 'MAX_ATTEMPTS': '2'}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(batch, 'fingerprint', return_value=('fixed-source', {})), \
                    patch.object(batch.subprocess, 'check_output', return_value='sha256:image'), \
                    patch.object(batch.subprocess, 'run', side_effect=fake_run):
                self.assertEqual(batch.main(), 0)
                self.assertEqual(count['generation'], 2)
                self.assertEqual(count['validation'], 1)
                attempts = list((root / 'datasets/test/.attempts/episode-000').glob('*/attempt.json'))
                self.assertEqual(len(attempts), 2)
                records = [json.loads(p.read_text()) for p in attempts]
                self.assertEqual(sum(r['validated'] for r in records), 1)
                self.assertTrue(all('allocated_gpu_wall_s' in r for r in records))
                self.assertEqual(batch.main(), 0)
                self.assertEqual(count['generation'], 2)
                self.assertEqual(count['validation'], 2)
                self.assertEqual(count['ownership'], 4)
                self.assertEqual(count['cleanup'], 8)

    def test_persistent_partial_worker_validates_completed_and_retries_individually(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counts = {'workers': 0, 'individual': [], 'validations': []}

            def local(path):
                return root / path.removeprefix('/data/')

            def artifact(private, valid):
                private.mkdir()
                (private / 'manifest.json').write_text(json.dumps({'status': 'success', 'valid': valid}))

            def fake_run(command, **kwargs):
                if command[:2] != ['docker', 'run'] or '/usr/bin/chown' in command:
                    return subprocess.CompletedProcess(command, 0)
                if '--episode-plan' in command:
                    counts['workers'] += 1
                    plan = json.loads(local(command[command.index('--episode-plan') + 1]).read_text())
                    self.assertEqual(len(plan), 3)
                    self.assertEqual(kwargs['timeout'], 123)
                    for entry in plan:
                        lock_path = root / 'datasets/test/.claims' / f'episode-{entry["episode_id"]:03d}.lock'
                        self.assertIsNone(batch.claim(lock_path))
                    artifact(local(plan[0]['attempt_dir']), True)
                    artifact(local(plan[1]['attempt_dir']), False)
                    return subprocess.CompletedProcess(command, 1)
                if '--attempt-dir' in command:
                    episode_id = int(command[command.index('--episode-id') + 1])
                    counts['individual'].append(episode_id)
                    artifact(local(command[command.index('--attempt-dir') + 1]), True)
                    return subprocess.CompletedProcess(command, 0)
                path = local(command[command.index('--episode') + 1])
                counts['validations'].append(path.name)
                return subprocess.CompletedProcess(command, 0 if json.loads((path / 'manifest.json').read_text())['valid'] else 1)

            env = {'RUNTIME_ROOT': tmp, 'DATA_ROOT': tmp, 'DATASET_NAME': 'test',
                   'EPISODE_START': '0', 'EPISODE_END': '2', 'MAX_ATTEMPTS': '2',
                   'PERSISTENT_EPISODES_PER_WORKER': '3', 'PERSISTENT_WORKER_TIMEOUT_SECONDS': '123'}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(batch, 'fingerprint', return_value=('fixed-source', {})), \
                    patch.object(batch.subprocess, 'check_output', return_value='sha256:image'), \
                    patch.object(batch.subprocess, 'run', side_effect=fake_run):
                self.assertEqual(batch.main(), 0)
                self.assertEqual(counts['workers'], 1)
                self.assertEqual(counts['individual'], [1, 2])
                self.assertEqual(len(list((root / 'datasets/test').glob('episode-*/publication.json'))), 3)
                ledgers = [json.loads(p.read_text()) for p in (root / 'datasets/test/.workers').glob('*/worker.json')]
                for ledger in ledgers:
                    records = [json.loads((root / 'datasets/test' / a / 'attempt.json').read_text()) for a in ledger['attempts']]
                    self.assertEqual(sum(r['allocated_gpu_wall_s'] for r in records), ledger['allocated_gpu_wall_s'])
                cohort = next(v for v in ledgers if v['persistent'])
                records = [json.loads((root / 'datasets/test' / a / 'attempt.json').read_text()) for a in cohort['attempts']]
                self.assertEqual([r['validated'] for r in records], [True, False, False])
                self.assertEqual(records[2]['allocated_gpu_wall_s'], 0)
                self.assertEqual(batch.main(), 0)
                self.assertEqual(counts['workers'], 1)
                self.assertEqual(counts['individual'], [1, 2])


if __name__ == '__main__':
    unittest.main()
