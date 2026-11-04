"""Fail when a PSYPACT lambda file is a copy of the common-python file at the same path."""

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND / 'common-python'))

from copy_sync_tests.copied_file_text import (  # noqa: E402
    normalize_copied_body,
    parse_origin_comment,
    strip_import_lines,
)

_SKIP = frozenset({'tests', '.shared-stage', 'common', '__pycache__', '.ruff_cache', '.pytest_cache'})


def _comparable_body(path: Path, *, shared: bool) -> str:
    text = path.read_text(encoding='utf-8')
    parsed = parse_origin_comment(text)
    if parsed is not None:
        text = parsed[2]
    if shared:
        text = normalize_copied_body(text)
    text = strip_import_lines(text)
    text = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
    return re.sub(r'\s+', ' ', text).strip()


def test_psypact_python_does_not_duplicate_common_python():
    app_root = BACKEND / 'psypact-app' / 'lambdas' / 'python'
    shared_root = BACKEND / 'common-python' / 'lambdas'
    duplicates = []
    for path in sorted(app_root.rglob('*.py')):
        if any(part in _SKIP for part in path.parts):
            continue
        counterpart = shared_root / path.relative_to(app_root)
        if not counterpart.is_file():
            continue
        if _comparable_body(path, shared=False) == _comparable_body(counterpart, shared=True):
            duplicates.append(str(path.relative_to(app_root)))

    if duplicates:
        message = (
            'These PSYPACT files match common-python once imports and comments are removed. Delete them:\n'
            + '\n'.join(duplicates)
        )
        raise AssertionError(message)
