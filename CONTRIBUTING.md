# Contributing

Contributions should preserve the separation between high-level policy actions and PX4's low-level stabilization.

Before opening a pull request:

1. install CPU test dependencies with `python -m pip install -r requirements-test.txt`;
2. run `make check` and `make test` (Node.js 22+ for viewer isolation tests);
3. preserve the frozen split registry and asset lock unless intentionally versioning them;
4. smoke-test at least one complete PX4 episode for simulator changes;
5. run the deep validator for schema, recorder, mission, or environment changes;
6. visually inspect the playback viewer for frontend changes.

Do not commit downloaded assets, generated episodes, simulator caches, credentials, or machine-specific paths.
