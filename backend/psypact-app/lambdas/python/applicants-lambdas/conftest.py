import sys
from pathlib import Path

# This directory is the pytest root when the suite is launched from the app root.
# Common code and the shared runtime live outside it.
_AREA_DIR = Path(__file__).resolve().parent
_COMMON_DIR = _AREA_DIR.parent / 'common'
_COMMON_PYTHON = _AREA_DIR.parents[4] / 'common-python'
for _path in (_AREA_DIR, _COMMON_DIR, _COMMON_PYTHON):
    if _path.is_dir():
        _path_text = str(_path)
        if _path_text not in sys.path:
            sys.path.insert(0, _path_text)

from cc_common.test_shared_handlers import install_shared_handler_fallback  # noqa: E402

install_shared_handler_fallback(_AREA_DIR)
