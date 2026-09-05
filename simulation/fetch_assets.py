#!/usr/bin/env python3
"""Download the pinned CC0 Poly Haven assets used by UAV simulation v2."""

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path


API = "https://api.polyhaven.com"
USER_AGENT = "YerevaNN-VLN-Simulations/1.0 (+https://github.com/YerevaNN/VLN-Simulations)"

DEFAULT_LOCK = Path(__file__).resolve().parents[1] / "configs" / "assets.lock.json"


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def locked_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError(f"Asset path escapes root: {relative}")
    return path


def matches_lock(path, item):
    return (path.is_file() and path.stat().st_size == item["bytes"]
            and file_sha256(path) == item["sha256"])


def sync_locked_assets(root, lock_path=DEFAULT_LOCK, verify_only=False):
    """Resolve exact bytes without requesting the mutable upstream asset catalog."""
    lock_path = Path(lock_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("schema_version") != "uav-assets-lock-v1":
        raise ValueError("Unsupported asset lock schema")
    paths = [item["path"] for item in lock["files"]]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate asset path in lock")
    for item in lock["files"]:
        target = locked_path(root, item["path"])
        if matches_lock(target, item):
            continue
        if verify_only:
            raise ValueError(f"Missing or altered locked asset: {item['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".asset-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                request = urllib.request.Request(item["source_url"], headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=180) as response:
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if not matches_lock(Path(temp_name), item):
                raise ValueError(f"Downloaded bytes differ from lock: {item['path']}")
            os.replace(temp_name, target)
        finally:
            Path(temp_name).unlink(missing_ok=True)
    if not verify_only:
        manifest = dict(lock["source_manifest"])
        manifest["asset_lock_sha256"] = file_sha256(lock_path)
        manifest["content_hash_algorithm"] = "sha256"
        # Keep the established per-asset layout while adding strong content hashes.
        entries = {item["path"]: item for item in lock["files"]}
        for asset in manifest["assets"]:
            base = Path({"model": "models", "texture": "textures", "hdri": "hdri"}[asset["kind"]]) / asset["id"]
            for item in asset["files"]:
                item["sha256"] = entries[str(base / item["path"])]["sha256"]
        target = Path(root) / "asset_manifest.json"
        fd, temp_name = tempfile.mkstemp(prefix=".manifest-", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        finally:
            Path(temp_name).unlink(missing_ok=True)
    return {"asset_lock_sha256": file_sha256(lock_path), "verified_files": len(paths)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="/mnt/frtn/uav-sim/assets/polyhaven-v2")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--verify-only", action="store_true", help="Check exact local bytes without writes or network requests")
    args = parser.parse_args()
    print(json.dumps(sync_locked_assets(args.output_root, args.lock, args.verify_only), sort_keys=True))


if __name__ == "__main__":
    main()
