from __future__ import annotations

import shutil
from pathlib import Path


def default_common_lambdas_source() -> Path:
    """Return backend/common-python/common_lambdas, resolved from this file's location."""
    # common_constructs/ -> common-cdk/ -> backend/common-python/common_lambdas
    return Path(__file__).resolve().parents[2] / 'common-python' / 'common_lambdas'

### NOTE - this will eventually go away once we extract common-python to a pypi package.
def sync_common_lambdas_into_layer_entry(
    entry: str | Path,
    *,
    source: str | Path | None = None,
) -> Path | None:
    """Copy ``common_lambdas`` into a common-lambda entry directory for CDK layer bundling.

    ``backend/common-python`` is the only copy in git. PythonLayerVersion can only
    package files under its ``entry`` path, so PsyPact materializes the package there at
    synth time (``include_shared_python=True``). The destination is gitignored.

    Returns the destination path when a copy is performed, otherwise ``None``.
    Skips test fixture directories so unit tests do not mutate fixtures.
    """
    entry_path = Path(entry)
    if not entry_path.is_dir():
        return None
    if 'fixtures' in entry_path.resolve().parts:
        return None

    source_path = Path(source) if source is not None else default_common_lambdas_source()
    if not source_path.is_dir():
        raise FileNotFoundError(
            f'Expected shared lambda package at {source_path}. '
            'Keep common_lambdas in backend/common-python; it is copied into the common layer at synth.'
        )

    dest = entry_path / 'common_lambdas'
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        source_path,
        dest,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.ruff_cache'),
    )
    return dest


_STAGE_IGNORE = shutil.ignore_patterns('tests', '__pycache__', '*.pyc', '.ruff_cache', '.pytest_cache', 'entries')


def stage_shared_lambda_overlay(lambda_dir: str) -> str:
    """Build a gitignored Lambda zip root from common-python, then the app directory.

    common-python/lambdas/<lambda_dir> is copied first. The app's lambdas/python/<lambda_dir>
    is copied over it, so an app file replaces the shared file at the same path. Tests are
    left out of the zip. The result is lambdas/python/.shared-stage/<lambda_dir>, which is gitignored.
    """
    shared_dir = default_common_lambdas_source().parent / 'lambdas' / lambda_dir
    app_dir = Path('lambdas', 'python', lambda_dir)
    dest = Path('lambdas', 'python', '.shared-stage', lambda_dir)
    if dest.exists():
        shutil.rmtree(dest)
    if shared_dir.is_dir():
        shutil.copytree(shared_dir, dest, ignore=_STAGE_IGNORE)
    else:
        dest.mkdir(parents=True)
    if app_dir.is_dir():
        shutil.copytree(app_dir, dest, ignore=_STAGE_IGNORE, dirs_exist_ok=True)
    return str(dest)
