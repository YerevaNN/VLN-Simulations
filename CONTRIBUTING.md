# Contributing

Contributions should preserve the separation between high-level policy actions and PX4's low-level stabilization.

Before opening a pull request:

1. run `python -m py_compile simulation/*.py viewer/app.py`;
2. run `bash -n scripts/*.sh`;
3. run `git diff --check`;
4. smoke-test at least one complete PX4 episode for simulator changes;
5. run the deep validator for schema, recorder, mission, or environment changes;
6. visually inspect the playback viewer for frontend changes.

Do not commit downloaded assets, generated episodes, simulator caches, credentials, or machine-specific paths.
