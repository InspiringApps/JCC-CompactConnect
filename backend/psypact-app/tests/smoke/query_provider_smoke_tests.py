#!/usr/bin/env python3
"""PsyPact entry point for the shared query-provider smoke test.

The shared private-read test hardcodes compact aslp. This script replaces that
one test and calls the other two from the shared copy.
"""

import requests
from _common_smoke import add_common_python_to_path
from deepdiff import DeepDiff

add_common_python_to_path()

from common_smoke_test import query_provider_smoke_tests as shared  # noqa: E402
from smoke_common import (  # noqa: E402
    SmokeTestFailureException,
    call_provider_users_me_endpoint,
    create_test_staff_user,
    delete_test_staff_user,
    get_staff_user_auth_headers,
    load_smoke_test_env,
)


def get_provider_data_with_read_private_access_smoke_test(test_staff_user_id: str):
    """Read private provider fields using the signed-in provider's compact."""
    test_user_profile = call_provider_users_me_endpoint()
    provider_id = test_user_profile['providerId']
    compact = test_user_profile['compact']
    staff_users_headers = get_staff_user_auth_headers(shared.TEST_STAFF_USER_EMAIL)
    patch_body = {'permissions': {compact: {'actions': {'readPrivate': True}}}}
    patch_response = requests.patch(
        url=shared.config.api_base_url + f'/v1/compacts/{compact}/staff-users/{test_staff_user_id}',
        headers=staff_users_headers,
        json=patch_body,
        timeout=10,
    )

    if patch_response.status_code != 200:
        raise SmokeTestFailureException(f'Failed to PATCH staff user permissions. Response: {patch_response.json()}')
    shared.logger.info('Successfully updated staff user permissions.')

    staff_users_headers = get_staff_user_auth_headers(shared.TEST_STAFF_USER_EMAIL)
    get_provider_response = requests.get(
        url=shared.config.api_base_url + f'/v1/compacts/{compact}/providers/{provider_id}',
        headers=staff_users_headers,
        timeout=10,
    )

    if get_provider_response.status_code != 200:
        raise SmokeTestFailureException(f'Failed to GET staff user. Response: {get_provider_response.json()}')

    shared.logger.info('Received success response from GET endpoint')

    provider_object = get_provider_response.json()
    # because this test staff user is a compact admin, there will be download links present for the
    # military affiliation files, so we need to account for those here by removing them from the
    # list of military records and checking the links to verify they are valid
    for record in provider_object['militaryAffiliations']:
        if 'downloadLinks' in record.keys():
            download_links = record.pop('downloadLinks')
            for download_link in download_links:
                if 'url' not in download_link or 'fileName' not in download_link:
                    raise SmokeTestFailureException(f'Invalid download link structure: {download_link}')

                shared.logger.info(f'downloading test file from {download_link["url"]}')
                download_response = requests.get(download_link['url'], timeout=30)
                if download_response.status_code != 200:
                    raise SmokeTestFailureException(
                        f'Failed to download file from pre-signed URL. Status code: {download_response.status_code}, '
                        f'URL: {download_link["url"]}, File name: {download_link["fileName"]}'
                    )
                shared.logger.info(f'Successfully downloaded file: {download_link["fileName"]}')
        else:
            raise SmokeTestFailureException(
                f'Missing expected download links for military affiliation. Military affiliation: {record}'
            )

    if provider_object != test_user_profile:
        raise SmokeTestFailureException(
            f'Provider object does not match the profile.\n{DeepDiff(test_user_profile, provider_object)}'
        )

    shared.logger.info('Successfully fetched expected user profile.')


if __name__ == '__main__':
    load_smoke_test_env()
    provider_user_profile = call_provider_users_me_endpoint()
    # The shared tests read this global from their own module.
    shared.provider_user_profile = provider_user_profile
    provider_compact = provider_user_profile['compact']
    # ensure the test staff user is in the same compact as the test provider user without 'readPrivate' permissions
    test_user_sub = create_test_staff_user(
        email=shared.TEST_STAFF_USER_EMAIL,
        compact=provider_compact,
        jurisdiction='oh',
        permissions={'actions': {'admin'}, 'jurisdictions': {'oh': {'write', 'admin'}}},
    )
    try:
        shared.get_general_provider_user_data_smoke_test()
        shared.query_provider_user_smoke_test()
        get_provider_data_with_read_private_access_smoke_test(test_staff_user_id=test_user_sub)
        shared.logger.info('Query provider smoke tests passed')
    except SmokeTestFailureException as e:
        shared.logger.error(f'Query provider smoke tests failed: {str(e)}')
    finally:
        delete_test_staff_user(shared.TEST_STAFF_USER_EMAIL, user_sub=test_user_sub, compact=provider_compact)
