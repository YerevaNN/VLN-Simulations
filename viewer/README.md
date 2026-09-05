# UAV Simulation POC Viewer

Playback UI for published UAV episodes. It synchronizes RGB, recorded controls, state and subgoals. New episodes display positions from `scene_inventory.json`; historical episodes without that file visibly label the map as a legacy approximation.

The index loads 100 episodes per page and supports numeric IDs beyond 999. Each episode initially loads a maximum of 2,001 samples per table for its overview. Playback fetches overlapping 30-second chunks, with timestamp predicates that can skip Parquet row groups. Map and chart backgrounds are cached until episode/size changes, and generation tokens prevent stale requests or images from populating another episode. Overview paths/charts are downsampled; playback controls and telemetry retain recorded sample resolution within the current chunk. Very short transients may not appear in the overview chart.

`GET /api/episodes?offset=0&limit=100` returns `items`, `total`, and `next_offset`. `GET /api/episodes/<id>` returns the overview; `GET /api/episodes/<id>/chunks/<n>` returns timeline data. Consumers of the former flat index/full-timeline API must migrate. `scripts/export_static_viewer.py` exports this same paginated/chunked structure for static hosting.

Published episode directories are expected to be immutable. The worker uses bounded in-process timeline caching; replace/restart it when deliberately changing an existing episode. The directory listing still scans episode names, so a production object store should supply a catalog index. Parquet files without timestamp statistics remain readable but cannot benefit from row-group pruning.

CPU regression tests: `python -m unittest discover -s viewer -v` (Flask/PyArrow installed), plus `node viewer/test_app.js`. These cover pagination, large IDs, time boundaries, stored scene positions, static export layout, and stale asynchronous callbacks.

## Deployment

From the repository root, set the dataset location and launch the read-only container:

```bash
DATASET_ROOT=/path/to/natural-valley-v2 PORT=8787 ./scripts/serve_viewer.sh
```

Health endpoint: `http://HOST:8787/api/health`. The reference deployment is available at [ap.yc2.io:8787](http://ap.yc2.io:8787).

## Archival shards

On Linux, `python3 scripts/pack_dataset.py --dataset-root /path/to/dataset --output /path/to/new-archive` writes uncompressed tar shards (4 GiB target, at most 50,000 members) and JSON byte-offset indexes. Only episodes with a valid `publication.json` receipt matching their manifest are included; old episodes need validation/publication first. Files are stored byte-for-byte, including JPEGs, tables, logs, and exports. A single oversized file can exceed the target.

Each index records member path, size, offset and SHA-256; `archive-manifest.json` additionally hashes each tar and index. `read_indexed()` demonstrates direct random reads with checksum verification; an object-store HTTP Range request can retrieve the same byte range without extracting thousands of files. The existing viewer still reads the unpacked dataset: archive-backed viewer/training loaders are a subsequent integration, not implied by packing.

Packing writes to a private sibling directory, synchronizes files, then publishes with Linux atomic no-overwrite rename. It rejects symlinks and changing input files, retains all sources, and refuses an existing output. A process crash may leave a `.packing.lock` and private directory; inspect those before removing that specific stale attempt. No production dataset is packed automatically. Test with `python3 -m unittest discover -s tests -p test_pack_dataset.py -v`.
