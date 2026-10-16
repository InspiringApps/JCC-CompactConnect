# Common Python

This directory is the only git source of truth for shared Python used by PSYPACT:

- `common_lambdas/` — common layer (Cosmetology copies, JCC mixins, PSYPACT wrappers)
- `lambdas/` — copied lambda packages PSYPACT deploys with `PythonFunction(shared=True)`
- `lambdas/common/tests/resources/` — Cosmetology (plus JCC military) fixtures so copied lambda tests keep their `../common/tests/resources` paths

PsyPact is currently the only consumer. Do not commit `common_lambdas` under `psypact-app/lambdas/`. At CDK synth,
`PythonCommonLayerVersions(include_shared_python=True)` copies `common_lambdas/` into `lambdas/python/common/` so the
common Lambda layer can bundle it. That copy is gitignored.

PsyPact tests import `common_lambdas` by putting this directory on `sys.path` (the same approach used for `common-cdk`).

Copied-file drift vs Cosmetology/JCC sources is checked by the tests in `copy_sync_tests/` (see that directory's README). Treat those copies like a semantically versioned package: do not change a file unless the change is backwards compatible with existing usages. Each backend project's `bin/run_tests.sh` and CodePipeline synth run the copy-sync suite.
