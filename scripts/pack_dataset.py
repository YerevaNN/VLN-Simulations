#!/usr/bin/env python3
"""Pack immutable published episodes into seekable, checksummed tar shards.

The JSON index gives byte offsets for direct local seeks or object-store Range
requests. JPEG/Parquet bytes are stored unchanged, without tar compression.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import tempfile

EPISODE_RE = re.compile(r"episode-\d{3,}")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def publish_directory(source, destination):
    """Linux atomic rename with RENAME_NOREPLACE (even for empty destinations)."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise RuntimeError("Atomic no-overwrite publication requires Linux renameat2")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json(path, value):
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def source_files(root):
    for parent, dirs, names in os.walk(root, followlinks=False):
        dirs.sort()
        for name in dirs + names:
            if (Path(parent) / name).is_symlink():
                raise ValueError(f"Symlinks are not archival inputs: {Path(parent) / name}")
        for name in sorted(names):
            path = Path(parent) / name
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError(f"Not a regular file: {path}")
            yield path


class HashReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, size=-1):
        block = self.stream.read(size)
        self.digest.update(block)
        self.count += len(block)
        return block


def pack_dataset(dataset, output, max_bytes=4 * 1024**3, max_files=50000):
    dataset, output = Path(dataset).resolve(), Path(output).absolute()
    if max_bytes < 10240 or max_files < 1:
        raise ValueError("Shard size must be at least 10240 bytes and max-files positive")
    if output.exists():
        raise FileExistsError(output)
    if output == dataset or dataset in output.parents:
        raise ValueError("Archive output must be outside the input dataset")
    output.parent.mkdir(parents=True, exist_ok=True)
    claim = output.with_name(output.name + ".packing.lock")
    descriptor = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    staging = None
    archive = None
    try:
        if output.exists():
            raise FileExistsError(output)
        staging = Path(tempfile.mkdtemp(prefix="." + output.name + ".packing-", dir=output.parent))
        shards, episodes, entries = [], [], []
        shard_path = None
        def finish_shard():
            nonlocal archive, entries
            if archive is None:
                return
            archive.close()
            archive = None
            # GNU long-name headers are included in offset_data automatically.
            with tarfile.open(shard_path, "r:") as reader:
                for member, entry in zip(reader, entries):
                    if member.name != entry["path"] or member.size != entry["size"]:
                        raise ValueError("Archive/index member mismatch")
                    entry["offset"] = member.offset_data
            with shard_path.open("rb") as stream:
                os.fsync(stream.fileno())
            index_name = shard_path.name + ".index.json"
            write_json(staging / index_name, {"version": 1, "archive": shard_path.name, "entries": entries})
            shards.append({"archive": shard_path.name, "size": shard_path.stat().st_size,
                           "sha256": sha256(shard_path), "index": index_name,
                           "index_sha256": sha256(staging / index_name), "files": len(entries)})
            entries = []
        candidates = sorted((p for p in dataset.iterdir() if EPISODE_RE.fullmatch(p.name)), key=lambda p: int(p.name.split("-")[-1]))
        for episode in candidates:
            if episode.is_symlink() or not episode.is_dir():
                raise ValueError(f"Episode must be a real directory: {episode}")
            receipt_path = episode / "publication.json"
            if not receipt_path.exists():
                continue  # Private/incomplete or historical episodes require explicit validation/publication first.
            receipt = json.loads(receipt_path.read_text())
            manifest_hash = sha256(episode / "manifest.json")
            if receipt.get("validation_passed") is not True or receipt.get("manifest_sha256") != manifest_hash:
                raise ValueError(f"Invalid publication receipt: {episode}")
            episodes.append({"episode": episode.name, "manifest_sha256": manifest_hash})
            for path in source_files(episode):
                before = path.stat()
                estimated = 512 + ((before.st_size + 511) // 512) * 512 + 10240
                if archive is not None and entries and (archive.offset + estimated > max_bytes or len(entries) >= max_files):
                    finish_shard()
                if archive is None:
                    shard_path = staging / f"shard-{len(shards):06d}.tar"
                    archive = tarfile.open(shard_path, "x", format=tarfile.GNU_FORMAT)
                relative = path.relative_to(dataset).as_posix()
                info = archive.gettarinfo(str(path), arcname=relative)
                with path.open("rb") as stream:
                    hashed = HashReader(stream)
                    archive.addfile(info, hashed)
                after = path.stat()
                if hashed.count != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                    raise ValueError(f"Source changed while packing: {path}")
                entries.append({"path": relative, "size": hashed.count, "sha256": hashed.digest.hexdigest()})
            if sha256(episode / "manifest.json") != manifest_hash:
                raise ValueError(f"Manifest changed while packing: {episode}")
        finish_shard()
        if not episodes:
            raise ValueError("No validated published episodes found")
        catalog = {"version": 1, "format": "uncompressed-tar-with-byte-index", "dataset": dataset.name,
                   "episodes": episodes, "shards": shards, "max_bytes_target": max_bytes,
                   "note": "A single large member may exceed the shard target; source files are unchanged."}
        write_json(staging / "archive-manifest.json", catalog)
        if output.exists():
            raise FileExistsError(output)
        fsync_directory(staging)
        publish_directory(staging, output)
        staging = None
        fsync_directory(output.parent)
        return catalog
    finally:
        if archive is not None:
            archive.close()
        if staging is not None:
            shutil.rmtree(staging)
        claim.unlink()


def read_indexed(archive, entry):
    """Example random-access reader: a Range GET can replace seek/read remotely."""
    with Path(archive).open("rb") as stream:
        stream.seek(entry["offset"])
        data = stream.read(entry["size"])
    if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError("Indexed member checksum mismatch")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-shard-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--max-files", type=int, default=50000)
    args = parser.parse_args()
    result = pack_dataset(args.dataset_root, args.output, args.max_shard_bytes, args.max_files)
    print(json.dumps({"episodes": len(result["episodes"]), "shards": len(result["shards"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
