#!/usr/bin/env python3
"""PsyPact entry point for the shared account-recovery smoke test."""

from _common_smoke import add_common_python_to_path

add_common_python_to_path()

from common_smoke_test.account_recovery_smoke_tests import (  # noqa: E402
    test_account_recovery_flow,
    test_account_recovery_wrong_password,
)
from smoke_common import load_smoke_test_env  # noqa: E402

if __name__ == '__main__':
    # Load environment variables from smoke_tests_env.json
    load_smoke_test_env()

    # Run tests
    test_account_recovery_wrong_password()
    test_account_recovery_flow()
