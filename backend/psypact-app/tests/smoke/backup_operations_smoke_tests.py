#!/usr/bin/env python3
"""PsyPact entry point for the shared backup smoke test."""

from _common_smoke import add_common_python_to_path

add_common_python_to_path()

from common_smoke_test.backup_operations_smoke_tests import main  # noqa: E402

if __name__ == '__main__':
    main()
