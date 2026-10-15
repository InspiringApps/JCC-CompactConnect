"""Re-export shared smoke helpers. PsyPact-only names are defined here."""

import json
import os

from _common_smoke import add_common_python_to_path

add_common_python_to_path()

from common_smoke_test.compact_connect_smoke_common import (  # noqa: E402
    call_provider_users_me_endpoint,
    get_provider_user_auth_headers_cached,
)
from common_smoke_test.cosmetology_smoke_common import (  # noqa: E402
    COMPACTS,
    JURISDICTIONS,
    LICENSE_TYPES,
    SmokeTestFailureException,
    call_provider_details_endpoint,
    call_public_get_provider,
    call_public_query_providers,
    cleanup_test_provider_records,
    config,
    create_test_app_client,
    create_test_staff_user,
    delete_test_app_client,
    delete_test_staff_user,
    get_all_provider_database_records,
    get_api_base_url,
    get_client_auth_headers,
    get_client_credentials_token,
    get_data_events_dynamodb_table,
    get_lambda_client,
    get_license_type_abbreviation,
    get_provider_user_dynamodb_table,
    get_provider_user_records,
    get_rate_limiting_dynamodb_table,
    get_ssn_dynamodb_table,
    get_staff_user_auth_headers,
    get_user_tokens,
    logger,
    query_provider_by_name,
    wait_for_opensearch_sync,
    wait_for_provider_creation,
)

__all__ = [
    'COMPACTS',
    'JURISDICTIONS',
    'LICENSE_TYPES',
    'SmokeTestFailureException',
    'call_provider_details_endpoint',
    'call_provider_users_me_endpoint',
    'call_public_get_provider',
    'call_public_query_providers',
    'cleanup_test_provider_records',
    'config',
    'create_test_app_client',
    'create_test_staff_user',
    'delete_test_app_client',
    'delete_test_staff_user',
    'get_all_provider_database_records',
    'get_api_base_url',
    'get_client_auth_headers',
    'get_client_credentials_token',
    'get_data_events_dynamodb_table',
    'get_lambda_client',
    'get_license_type_abbreviation',
    'get_most_recently_issued_or_renewed_license',
    'get_provider_user_auth_headers_cached',
    'get_provider_user_dynamodb_table',
    'get_provider_user_records',
    'get_rate_limiting_dynamodb_table',
    'get_ssn_dynamodb_table',
    'get_staff_user_auth_headers',
    'get_user_tokens',
    'load_smoke_test_env',
    'logger',
    'query_provider_by_name',
    'wait_for_opensearch_sync',
    'wait_for_provider_creation',
]


def load_smoke_test_env():
    """Load smoke_tests_env.json from this directory, not from the shared copy."""
    with open(os.path.join(os.path.dirname(__file__), 'smoke_tests_env.json')) as env_file:
        env_vars = json.load(env_file)
        os.environ.update(env_vars)


def get_most_recently_issued_or_renewed_license(licenses: list[dict]) -> dict:
    """Select the license renewed most recently, otherwise the one issued most recently.

    The Cosmetology helper calls ProviderRecordUtility.find_most_recently_issued_or_renewed_license.
    The PsyPact lambda copy of that class does not define the method.
    """
    if not licenses:
        raise SmokeTestFailureException('No licenses found')

    def sort_key(license_record: dict) -> tuple[str, str]:
        return (license_record.get('dateOfRenewal') or '', license_record.get('dateOfIssuance') or '')

    return sorted(licenses, key=sort_key, reverse=True)[0]
