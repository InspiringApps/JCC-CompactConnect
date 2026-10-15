#!/usr/bin/env python3
"""PsyPact entry point for the shared military-affiliation smoke test."""

from _common_smoke import add_common_python_to_path

add_common_python_to_path()

from common_smoke_test.military_affiliation_smoke_tests import (  # noqa: E402
    test_military_affiliation_audit,
    test_military_affiliation_patch_update,
    test_military_affiliation_upload,
)
from smoke_common import load_smoke_test_env  # noqa: E402

if __name__ == '__main__':
    load_smoke_test_env()
    test_military_affiliation_upload()
    test_military_affiliation_patch_update()
    test_military_affiliation_audit()
