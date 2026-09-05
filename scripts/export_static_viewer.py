#!/usr/bin/env python3
"""Export the live UAV viewer as a self-contained static GitHub Pages bundle."""

import argparse
import json
import math
import shutil
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def fetch_json(url):
    with urllib.request.urlopen(url) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--viewer-url", default="http://127.0.0.1:8787")
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--viewer-static", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--quality", type=int, default=48)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--skip-images", action="store_true", help="Refresh viewer and JSON without reconverting existing preview frames")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "style.css", "app.js"):
        shutil.copy2(args.viewer_static / name, args.output / name)

    index_path = args.output / "index.html"
    index = index_path.read_text()
    index = index.replace('href="/style.css"', 'href="./style.css"')
    index = index.replace('src="/app.js"', 'src="./app.js"')
    index = index.replace(
        "Natural-environment assets by",
        "Display-optimized 512 px preview frames · Full 10 Hz dataset retained on YerevaNN infrastructure · Natural-environment assets by",
    )
    index_path.write_text(index)

    app_path = args.output / "app.js"
    app = app_path.read_text()
    app = "window.VIEWER_STATIC = true;\n" + app
    app_path.write_text(app)

    api_root = args.output / "api" / "episodes"
    api_root.mkdir(parents=True, exist_ok=True)
    episodes = []
    offset = 0
    while offset is not None:
        page = fetch_json(f"{args.viewer_url}/api/episodes?offset={offset}")
        (args.output / "api" / f"episodes-{offset}.json").write_text(json.dumps(page, separators=(",", ":")))
        episodes.extend(page["items"])
        offset = page["next_offset"]

    image_jobs = []
    seen_frames = set()
    for summary in episodes:
        episode_id = summary["id"]
        detail = fetch_json(f"{args.viewer_url}/api/episodes/{episode_id}")
        def rewrite_frames(payload):
            rewritten = []
            for timestamp, old_url in payload["frames"]:
                filename = Path(old_url).name
                relative = Path("frames") / episode_id / filename
                rewritten.append([timestamp, relative.as_posix()])
                if relative not in seen_frames:
                    seen_frames.add(relative)
                    image_jobs.append((args.dataset_root / episode_id / "frames" / filename, args.output / relative))
            payload["frames"] = rewritten
        rewrite_frames(detail)
        (api_root / f"{episode_id}.json").write_text(json.dumps(detail, separators=(",", ":")))
        chunk_root = api_root / episode_id / "chunks"
        chunk_root.mkdir(parents=True, exist_ok=True)
        for chunk in range(math.floor(detail["manifest"]["duration_s"] / detail["chunk_seconds"]) + 1):
            payload = fetch_json(f"{args.viewer_url}/api/episodes/{episode_id}/chunks/{chunk}")
            rewrite_frames(payload)
            (chunk_root / f"{chunk}.json").write_text(json.dumps(payload, separators=(",", ":")))

    def convert(job):
        source, target = job
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["convert", str(source), "-resize", f"{args.width}x", "-strip", "-quality", str(args.quality), str(target)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if not args.skip_images:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(convert, image_jobs))

    manifest = {
        "episodes": len(episodes),
        "frames": len(image_jobs),
        "preview_width_px": args.width,
        "jpeg_quality": args.quality,
        "source_dataset": args.dataset_root.name,
    }
    (args.output / "preview-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
