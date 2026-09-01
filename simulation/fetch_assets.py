#!/usr/bin/env python3
"""Download the pinned CC0 Poly Haven assets used by UAV simulation v2."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


API = "https://api.polyhaven.com"
USER_AGENT = "YerevaNN-VLN-Simulations/1.0 (+https://github.com/YerevaNN/VLN-Simulations)"

MODEL_IDS = [
    "boulder_01",
    "dead_tree_trunk",
    "fern_02",
    "fir_sapling",
    "grass_bermuda_01",
    "jacaranda_tree",
    "mountainside",
    "pine_sapling_small",
    "rock_07",
    "rock_09",
    "rock_moss_set_01",
    "shrub_02",
    "stone_01",
    "tree_stump_01",
]
TEXTURE_IDS = ["aerial_grass_rock", "forrest_ground_03", "ganges_river_pebbles"]
HDRI_IDS = ["drakensberg_solitary_mountain"]


def request_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download(url, path, expected_md5=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and expected_md5:
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        if digest == expected_md5:
            return
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response, path.open("wb") as stream:
        while chunk := response.read(1024 * 1024):
            stream.write(chunk)
    if expected_md5 and hashlib.md5(path.read_bytes()).hexdigest() != expected_md5:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"MD5 mismatch for {path}")


def choose(mapping, *path):
    value = mapping
    for key in path:
        value = value[key]
    return value


def fetch_file_entry(entry, root, relative_path):
    target = root / relative_path
    download(entry["url"], target, entry.get("md5"))
    return {
        "path": str(target.relative_to(root)),
        "bytes": target.stat().st_size,
        "md5": entry.get("md5"),
        "source_url": entry["url"],
    }


def fetch_model(asset_id, root):
    files = request_json(f"{API}/files/{asset_id}")
    entry = choose(files, "usd", "1k", "usd")
    asset_root = root / "models" / asset_id
    result = [fetch_file_entry(entry, asset_root, f"{asset_id}_1k.usdc")]
    for relative, dependency in entry.get("include", {}).items():
        result.append(fetch_file_entry(dependency, asset_root, relative))
    return {"id": asset_id, "kind": "model", "root_file": result[0]["path"], "files": result}


def find_texture_entry(files, names):
    for name in names:
        group = files.get(name)
        if not group:
            continue
        for resolution in ("2k", "1k"):
            formats = group.get(resolution, {})
            for extension in ("jpg", "png", "exr"):
                if extension in formats:
                    return formats[extension], extension, name
    return None


def fetch_texture(asset_id, root):
    files = request_json(f"{API}/files/{asset_id}")
    asset_root = root / "textures" / asset_id
    outputs = {}
    channels = {
        "diffuse": ("Diffuse", "diffuse"),
        "normal": ("nor_gl", "Normal GL", "normal_gl"),
        "roughness": ("Rough", "rough", "Roughness"),
    }
    result = []
    for channel, names in channels.items():
        selected = find_texture_entry(files, names)
        if not selected:
            continue
        entry, extension, source_key = selected
        item = fetch_file_entry(entry, asset_root, f"{channel}.{extension}")
        item["source_channel"] = source_key
        outputs[channel] = item["path"]
        result.append(item)
    if "diffuse" not in outputs:
        raise RuntimeError(f"No diffuse texture for {asset_id}")
    return {"id": asset_id, "kind": "texture", "channels": outputs, "files": result}


def fetch_hdri(asset_id, root):
    files = request_json(f"{API}/files/{asset_id}")
    entry = choose(files, "hdri", "2k", "hdr")
    asset_root = root / "hdri" / asset_id
    item = fetch_file_entry(entry, asset_root, f"{asset_id}_2k.hdr")
    return {"id": asset_id, "kind": "hdri", "root_file": item["path"], "files": [item]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="/mnt/frtn/uav-sim/assets/polyhaven-v2")
    args = parser.parse_args()
    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)
    catalog = request_json(f"{API}/assets")
    manifest = {
        "schema_version": "uav-sim-assets-v2",
        "source": "Poly Haven public API",
        "source_url": "https://polyhaven.com/",
        "license": "CC0 1.0 Universal",
        "license_url": "https://polyhaven.com/license",
        "api_credit": "Powered by Poly Haven",
        "assets": [],
    }
    for asset_id in MODEL_IDS:
        print(f"Fetching model {asset_id}", flush=True)
        item = fetch_model(asset_id, root)
        item["name"] = catalog[asset_id]["name"]
        item["authors"] = catalog[asset_id].get("authors", {})
        manifest["assets"].append(item)
    for asset_id in TEXTURE_IDS:
        print(f"Fetching texture {asset_id}", flush=True)
        item = fetch_texture(asset_id, root)
        item["name"] = catalog[asset_id]["name"]
        item["authors"] = catalog[asset_id].get("authors", {})
        manifest["assets"].append(item)
    for asset_id in HDRI_IDS:
        print(f"Fetching HDRI {asset_id}", flush=True)
        item = fetch_hdri(asset_id, root)
        item["name"] = catalog[asset_id]["name"]
        item["authors"] = catalog[asset_id].get("authors", {})
        manifest["assets"].append(item)
    (root / "asset_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Fetched {len(manifest['assets'])} assets into {root}", flush=True)


if __name__ == "__main__":
    main()
