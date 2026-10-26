#!/usr/bin/env python3
"""PsyPact entry point for the shared investigation smoke test.

The shared main() hardcodes compact cosm. This script sets the compact constant
the copied helpers read, then runs a PsyPact staff user across every jurisdiction.
"""

from _common_smoke import add_common_python_to_path

add_common_python_to_path()

from common_smoke_test import investigation_smoke_tests as shared  # noqa: E402
from smoke_common import JURISDICTIONS  # noqa: E402


def main():
    """Run all investigation smoke tests for PsyPact."""
    shared.INVESTIGATION_SMOKE_COMPACT = 'psypact'
    shared.logger.info('Starting investigation smoke tests...')

    staff_user_email = None
    staff_user_sub = None

    try:
        shared.load_smoke_test_env()
        shared.setup_test_environment()

        staff_user_email = 'test-investigation-admin@example.com'
        staff_user_sub = shared.create_test_staff_user(
            email=staff_user_email,
            compact='psypact',
            jurisdiction='co',
            permissions={
                'actions': {'admin'},
                'jurisdictions': {jurisdiction: {'admin'} for jurisdiction in JURISDICTIONS},
            },
        )

        auth_headers = shared.get_staff_user_auth_headers(staff_user_email)

        shared.setup_test_environment()
        shared.test_create_privilege_investigation(auth_headers)
        shared.test_close_privilege_investigation(auth_headers)

        shared.setup_test_environment()
        shared.test_create_privilege_investigation(auth_headers)
        shared.test_close_privilege_investigation_with_encumbrance(auth_headers)

        shared.setup_test_environment()
        shared.test_create_license_investigation(auth_headers)
        shared.test_close_license_investigation(auth_headers)

    except Exception as e:  # noqa: BLE001
        shared.logger.error(f'Investigation smoke tests failed: {str(e)}')
        raise
    finally:
        if staff_user_email and staff_user_sub:
            shared.delete_test_staff_user(staff_user_email, staff_user_sub, 'psypact')
        shared.clean_investigation_records()

    shared.logger.info('All investigation smoke tests passed!')


if __name__ == '__main__':
    main()
