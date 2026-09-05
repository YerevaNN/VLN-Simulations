"""Bounded recording and explicit temporal supervision; no simulator imports."""
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import time

class ImageWriter:
    """Copy ownership before submit; bounded backlog; propagate every error."""
    def __init__(self, max_pending=16):
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jpeg")
        self.pending = deque()
        self.max_pending = max_pending
        self.wait_s = 0.0

    def submit(self, path, rgb):
        from PIL import Image
        if len(self.pending) >= self.max_pending:
            start = time.perf_counter()
            self.pending.popleft().result()
            self.wait_s += time.perf_counter() - start
        pixels = rgb.copy()
        self.pending.append(self.pool.submit(lambda: Image.fromarray(pixels).save(path, quality=90, subsampling=1)))

    def close(self):
        try:
            while self.pending:
                self.pending.popleft().result()
        finally:
            self.pool.shutdown(wait=True, cancel_futures=True)

class ParquetRecorder:
    """Append bounded row groups without retaining a whole flight in memory."""
    def __init__(self, path, batch_size=2048):
        self.path, self.batch_size = path, batch_size
        self.rows, self.writer = [], None
    def append(self, row):
        self.rows.append(row)
        if len(self.rows) >= self.batch_size:
            self.flush()
    def flush(self):
        if not self.rows:
            return
        import pyarrow as pa
        import pyarrow.parquet as pq
        table = pa.Table.from_pylist(self.rows)
        if self.writer is None:
            self.writer = pq.ParquetWriter(self.path, table.schema)
        self.writer.write_table(table.cast(self.writer.schema))
        self.rows.clear()
    def close(self):
        try:
            self.flush()
        finally:
            if self.writer:
                self.writer.close()

def quantize_manual(command):
    roll, pitch, yaw, throttle = command
    clamp = lambda x, lo, hi: max(lo, min(hi, float(x)))
    return dict(x=int(clamp(pitch, -1, 1)*1000), y=int(clamp(roll, -1, 1)*1000),
                z=int(clamp((throttle+1)*500, 0, 1000)), r=int(clamp(yaw, -1, 1)*1000))

def training_rows(frames, actions, instruction, episode_id, rate):
    """Hold at observation availability plus future commands to chunk end (exclusive).
    Expert uses privileged state online. Receipt/application evidence is in ULog.
    """
    times = [row["sim_time_s"] for row in actions]
    if any(b < a for a,b in zip(times,times[1:])):
        raise ValueError("Action timestamps are not ordered")
    last = -float("inf")
    keys = ("roll", "pitch", "yaw", "throttle")
    for frame in frames:
        t = frame["sim_time_s"]
        if t-last < 1/rate-0.002:
            continue
        decision = frame.get("observation_time_s", t)
        if decision < t:
            raise ValueError("Observation availability precedes capture")
        idx = bisect_right(times,decision)-1
        if idx < 0 or decision >= times[-1]:
            continue
        end = min(decision+1/rate, times[-1])
        stop = bisect_right(times,end-1e-10)
        action = actions[idx]
        yield {"episode_id":episode_id,"timestamp_s":t,"decision_time_s":decision,"image":frame["path"],
               "mission":instruction,"subgoal":action["subgoal"],
               "action":{k:action[k] for k in keys},"action_time_s":times[idx],
               "alignment":"latest_transmitted_at_or_before_observation",
               "action_chunk_end_s":end,"action_chunk_duration_s":end-decision,
               "action_chunk":[{"timestamp_s":times[i], **{k:actions[i][k] for k in keys}}
                               for i in range(idx+1,stop)]}
        last=t


def source_lineage(repo_root, runtime_paths=()):
    """Fingerprint runnable inputs including dirty/untracked source, without secrets."""
    import hashlib
    import subprocess
    from pathlib import Path
    root = Path(repo_root)
    def commit(path):
        path = Path(path).resolve()
        repository = next((p for p in (path, *path.parents) if (p / ".git").exists()), path)
        try:
            return subprocess.run(["git", "-c", "safe.directory=" + str(repository), "-C", str(path), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            # Isaac's runtime image does not include git. Read only HEAD/refs,
            # supporting detached HEAD and normal packed-reference checkouts.
            try:
                git_dir = repository / ".git"
                if git_dir.is_file():
                    pointer = git_dir.read_text().strip()
                    if not pointer.startswith("gitdir: "):
                        return None
                    git_dir = (repository / pointer[8:]).resolve()
                head = (git_dir / "HEAD").read_text().strip()
                if not head.startswith("ref: "):
                    return head if len(head) == 40 and all(c in "0123456789abcdef" for c in head) else None
                ref = head[5:]
                if not ref.startswith("refs/") or ".." in ref.split("/"):
                    return None
                if (git_dir / ref).is_file():
                    return (git_dir / ref).read_text().strip()
                for line in (git_dir / "packed-refs").read_text().splitlines():
                    if line.endswith(" " + ref):
                        return line.split()[0]
            except OSError:
                pass
            return None
    files = {}
    # Deliberate allowlist: never enumerate credentials, generated datasets, assets.
    for folder in ("simulation", "scripts", "configs"):
        for path in sorted((root/folder).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".sh", ".json", ".yaml", ".yml", ".toml"):
                files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    canonical = "\n".join(f"{name}:{digest}" for name,digest in sorted(files.items()))
    runtime = {}
    for name, location in runtime_paths:
        path = Path(location)
        if path.is_file():
            path = path.parent
        runtime[name] = {"commit": commit(path)}
    return {"repository_commit": commit(root), "source_fingerprint_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "source_files_sha256": files, "runtime_repositories": runtime}


class ResetDeadline:
    """POSIX kernel deadline, including native calls that do not release the GIL.

    A stalled worker is terminated with SIGALRM; launcher preserves its private
    attempt and removes the whole container. Python error paths restore signals.
    """
    def __init__(self, seconds):
        if seconds <= 0:
            raise ValueError("reset deadline must be positive")
        self.seconds = seconds
    def __enter__(self):
        import signal
        import faulthandler
        self.previous = signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        faulthandler.dump_traceback_later(max(.01,self.seconds * 2 / 3))
        return self
    def __exit__(self, *exc):
        import signal
        import faulthandler
        signal.setitimer(signal.ITIMER_REAL, 0)
        faulthandler.cancel_dump_traceback_later()
        signal.signal(signal.SIGALRM, self.previous)
