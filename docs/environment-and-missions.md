# UAV Natural Valley Simulation V2

## Purpose

`natural-valley-v2` is the visual-diversity follow-on to the ten-episode UAV simulation POC. It preserves PX4 SITL, MAVLink `MANUAL_CONTROL`, the X500 v2 hardware target, 10 Hz forward RGB, 50 Hz gamepad-level actions, privileged vehicle state, raw MAVLink telemetry, and PX4 ULogs. It replaces the placeholder scene and repeated mission with a richer natural environment and ten different language-conditioned routes.

## Environment

The scene is a mountain valley built in Isaac Sim 5.1. A 1.3 km-square high-detail collision mesh covers the operating area, while a coarse 4.8 km-square visual terrain ring closes the horizon. It includes:

- a 161 × 161 collision terrain with a river-cut valley, side ridges, a high saddle, and an upstream rise;
- tiled 2K PBR grass-rock terrain and river-pebble materials;
- a winding water surface over a wider textured riverbed;
- instanced mature trees, conifer saplings, grasses, ferns, shrubs, deadwood, stumps, bank stones, boulders, and mossy rock sets;
- instanced photogrammetric rock faces forming valley walls;
- a timber footbridge, stone cairn, fire-lookout tower and beacon, waterfall, rockslide, cliff gate, and survey marker;
- a mountain HDR environment plus deterministic sun angle and intensity variation;
- route-aware vegetation exclusion around all ten flight paths so realism does not create camera occlusion or unsafe scripted transits;
- a 5 km camera far plane instead of Pegasus 5.1's 100 m default, explicit point-instancer bounds, a river extending beyond the routes, and a lower-density background forest so terrain and assets do not snap into view.

The POC's cones, spheres, flat-color terrain, sparse objects, and empty sky have been removed from this version.

## Asset Provenance

The pinned asset pack is stored on AP at `/mnt/frtn/uav-sim/assets/polyhaven-v2`. It contains 18 Poly Haven assets at moderate texture resolution, including photogrammetric rocks, stones, cliff faces, deadwood, vegetation, a mature tree, three PBR terrain materials, and a mountain HDR environment.

Poly Haven releases its assets under [CC0 1.0 Universal](https://polyhaven.com/license), including permission for AI training. The downloader uses the public API with a unique user agent and retains source URLs, authors, hashes, file sizes, license, and the required API credit in `asset_manifest.json`. Powered by Poly Haven.

The simulator consumes the downloaded files locally; episode generation does not depend on a live asset service after setup.

## Missions

| Episode | Mission ID | Task |
| ---: | --- | --- |
| 0 | `upper-river-waterfall-recon` | Follow the river, inspect the confluence, orbit the waterfall, and return along the opposite bank. |
| 1 | `western-forest-deadwood-survey` | Survey a conifer edge, circle a deadwood site, and cross a fern meadow. |
| 2 | `stone-cairn-photogrammetry-orbit` | Capture wide and close counter-rotating imaging arcs around the cairn. |
| 3 | `footbridge-structural-inspection` | Inspect both bridge faces and complete a clockwise overhead orbit. |
| 4 | `north-slope-rockslide-assessment` | Scan a rockslide west-to-east, orbit its largest boulder, and descend through the saddle. |
| 5 | `south-meadow-search-grid` | Execute a four-lane visual search and inspect a survey marker. |
| 6 | `fire-lookout-perimeter-check` | Climb the forest boundary, orbit the lookout, and inspect its beacon. |
| 7 | `confluence-branch-mapping` | Trace the main channel and both tributary branches before closing the loop. |
| 8 | `southern-cliff-gate-transit` | Transit a cliff gate, cross a high saddle, and image both rock faces. |
| 9 | `multi-landmark-valley-patrol` | Visit the bridge, cairn, lookout, waterfall, and cliff-gate approach in one patrol. |

Each `mission.json` contains a unique natural-language instruction, task type, named landmarks, subgoal-labelled ENU waypoints, seed, and landing index. Nominal routes range from 274 m to 1.03 km.

## Automation And Quality Gates

[`scripts/run_batch.sh`](../scripts/run_batch.sh) downloads the pinned assets if needed, generates episodes sequentially on the selected GPU, retries each failure up to three times, runs the deep dataset validator, and normalizes dataset ownership. Completed successful episodes are skipped on resume. Each simulator uses an isolated container network by default, so separate GPU shards cannot cross-talk through PX4/MAVLink ports.

Before the full batch, complete PX4 smoke missions validated the river and forest routes. Visual gates corrected asset units, missing alpha masks, material overrides, HDR composition, river width, camera angle, vegetation size, route clearance, and the Pegasus camera's overly short 100 m far-clipping plane.

The deep validator verifies decoded RGB images, timing, action bounds, mission completion, unique mission text, exports, checksums, MAVLink telemetry, and PX4 manual-control and actuator topics. It also requires the v2 environment version and CC0 provenance in every manifest.

## Known Limitations

- The vehicle remains a Pegasus Iris articulation acting as an X500 v2-class dynamics proxy.
- The water is a static rendering surface rather than a fluid simulation.
- Vegetation is static and is excluded from route corridors; wind animation and collision-aware replanning are not yet modeled.
- The scene uses curated procedural terrain rather than a surveyed real-world digital elevation model.
- Body-fixed RGB can still contain ground- or sky-heavy moments during strong attitude changes.
