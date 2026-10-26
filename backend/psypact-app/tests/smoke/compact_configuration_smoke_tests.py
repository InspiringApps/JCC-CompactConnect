#!/usr/bin/env python3
"""PsyPact entry point for the shared compact-configuration smoke test."""

from _common_smoke import add_common_python_to_path

add_common_python_to_path()

from common_smoke_test.compact_configuration_smoke_tests import (  # noqa: E402
    test_active_member_jurisdictions,
    test_compact_configuration,
    test_jurisdiction_configuration,
)
from smoke_common import load_smoke_test_env  # noqa: E402

if __name__ == '__main__':
    load_smoke_test_env()
    test_active_member_jurisdictions()
    test_compact_configuration()
    test_jurisdiction_configuration()
