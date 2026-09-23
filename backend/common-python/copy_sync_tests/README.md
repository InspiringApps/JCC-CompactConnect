# Copied-file sync tests

These tests compare the **text** of files copied into `backend/common-python` with the files they were copied from in Cosmetology and CompactConnect (JCC). They do not parse or execute Python. Allowed differences are only:

1. The origin comment at the top of the copy (`# Copied from …`).
2. Import lines, including the mechanical package rewrite `cc_common` → `common_lambdas`.

The compared region is the rest of the file after those headers/imports are removed. Non-UTF-8 fixtures (for example `bad.csv`) are compared as raw bytes.

Everything else in the copied file must match the source. Do not add compact-specific fields, methods, or types to a copied file.

## Treat copies like a published package

Until Cosmetology and CompactConnect officially migrate onto this directory, treat every copied file as if it were already a semantically versioned library used by multiple apps.

- **Compatible (patch / minor):** additive changes that preserve existing call and data contracts — new optional fields, new methods, new types, bugfixes that do not change current behavior. These may be recopied into `common-python`.
- **Breaking (major):** removing or renaming symbols, making an optional field required, changing return shapes, or changing side effects of an existing method. Do not copy a breaking change into the shared file unless every current consumer is updated in the same change. Prefer leaving the shared contract alone and putting the new behavior in a wrapper, subclass, or new module in the source app.

Do not change a copied file unless that change is backwards compatible with existing usages of the file.

## Why these tests exist

Copies here will lag any edits made in the source apps. These tests catch that drift so a shared file is only updated when the change can be taken as a compatible package update.

When it is time to migrate, the source projects should be able to switch to `common-python` without discovering that the “shared” file no longer matches what they already ship. Likewise, apps that consume the shared copy (PSYPACT today) must not edit a copied file to add compact-specific behavior. Extend the shared type, or override a shared method in a wrapper/subclass, so the original file stays a faithful, compatible copy.

The only file that cannot be a whole-file copy is the DataClient mixin (`jcc_data_client_mixin.py`): PSYPACT must keep Cosmetology `DataClient` (read-time privileges) while composing selected JCC DataClient methods onto the same instance. Cosmetology methods stay on the base class. That mixin is listed in `WHOLE_FILE_COMPARE_EXCLUSIONS` in `test_copied_files_match_sources.py`. Method-body fidelity is checked in `test_jcc_data_client_mixin.py`, which lists `PSYPACT_REQUIRED_JCC_DATA_CLIENT_METHODS` as the JCC DataClient surface those handlers call. Every other discovered copy is compared as a whole file. JCC modules that PSYPACT needs alongside a Cosmetology file of the same name live under an explicit `jcc_*` path and are still whole-file copies of their JCC source.

To skip a new file, add it to `WHOLE_FILE_COMPARE_EXCLUSIONS` with a reason that names the PSYPACT incompatibility; do not broaden the scanner. Do not splice a second lineage into a file that claims a single origin.

Each exclusion needs its own test file, not only a skip. Whole-file copies from a single source are covered by `test_copied_files_match_sources.py`. A file that combines behavior from more than one project (for example a method-body mixin) needs unique setup: which methods belong in the partial copy, which source those bodies must match, and which names must remain on the other project's whole file. Put that in a dedicated test module for that excluded file. Do not add another mixed-lineage file's checks to `test_jcc_data_client_mixin.py`; that module is only for the DataClient mixin.

## If a test fails

1. **Source app changed a copied file.** Re-copy into `common-python` only if the change is backwards compatible with existing usages. If it is not, keep the old contract in the shared module and put the new behavior in the source app (wrapper, subclass, or new module).
2. **Copy was edited by hand.** Restore it from the source. Compact-specific behavior belongs in a wrapper, not in the copied file.
3. **DataClient mixin drifted.** Re-run `_extract_jcc_data_client_mixin.py`. Do not edit mixin method bodies by hand. Re-extract only when the JCC method change is backwards compatible with existing callers.

## How they run

From `backend/common-python`:

```bash
bin/run_copy_sync_tests.sh
```

Each backend project (`psypact-app`, `cosmetology-app`, `compact-connect`, `social-work-app`) runs the same script from `bin/run_tests.sh` before pytest. GitHub `Check-Common-Python` runs it on `backend/common-python` PRs. Each compact's CodePipeline synth step runs it before `cdk synth`.
