import sys
from pathlib import Path

COMMON_PYTHON = Path(__file__).resolve().parents[3] / 'common-python'


def add_common_python_to_path() -> None:
    """Let entry scripts import common_smoke_test without hiding this directory's config."""
    path = str(COMMON_PYTHON)
    if path not in sys.path:
        sys.path.append(path)
