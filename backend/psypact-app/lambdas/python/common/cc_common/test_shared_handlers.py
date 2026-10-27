"""Let PSYPACT tests import handler modules that now live only in common-python.

The Lambda zip is built by copying common-python and then the PSYPACT directory, so a
deleted PSYPACT file is the common-python file at runtime. Unit tests run against the
PSYPACT tree, where that file is absent. This finder supplies the missing module without
putting the common-python lambda directory on sys.path, which would hide the PSYPACT
handlers package.
"""

import importlib.util
import sys
from pathlib import Path


def install_shared_handler_fallback(area_dir: Path) -> None:
    shared = area_dir.parents[3] / 'common-python' / 'lambdas' / area_dir.name
    local_handlers = area_dir / 'handlers'
    shared_handlers = shared / 'handlers'
    if not shared.is_dir():
        return

    if not local_handlers.is_dir() and str(shared) not in sys.path:
        sys.path.append(str(shared))

    if not shared_handlers.is_dir():
        return

    local_init = local_handlers / '__init__.py'
    locations = [str(path) for path in (local_handlers, shared_handlers) if path.is_dir()]

    class _SharedHandlerFinder:
        @staticmethod
        def find_spec(fullname, path, target=None):  # noqa: ARG004 the import hook signature is fixed
            if fullname == 'handlers':
                if local_init.is_file() or 'handlers' in sys.modules:
                    return None
                return importlib.util.spec_from_file_location(
                    'handlers',
                    shared_handlers / '__init__.py',
                    submodule_search_locations=locations,
                )
            prefix = 'handlers.'
            if not fullname.startswith(prefix) or fullname.count('.') != 1:
                return None
            module_name = fullname[len(prefix) :]
            if (local_handlers / f'{module_name}.py').is_file():
                return None
            shared_file = shared_handlers / f'{module_name}.py'
            if not shared_file.is_file():
                return None
            return importlib.util.spec_from_file_location(fullname, shared_file)

    sys.meta_path.insert(0, _SharedHandlerFinder)
