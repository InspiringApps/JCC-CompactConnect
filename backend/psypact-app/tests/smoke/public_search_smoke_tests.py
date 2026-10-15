#!/usr/bin/env python3
"""PsyPact entry point for the shared public-search smoke test.

The shared query filters by license number. This script queries by name and
matches licenseNumber on the response, because the deployed schema rejects licenseNumber.
"""

import copy

from _common_smoke import add_common_python_to_path

add_common_python_to_path()

from common_smoke_test import public_search_smoke_tests as shared  # noqa: E402
from smoke_common import (  # noqa: E402
    SmokeTestFailureException,
    call_public_get_provider,
    call_public_query_providers,
    get_all_provider_database_records,
    get_license_type_abbreviation,
    get_provider_user_dynamodb_table,
    load_smoke_test_env,
    logger,
    wait_for_opensearch_sync,
)


def _provider_name(provider_id: str, license_number: str) -> tuple[str, str]:
    records = get_all_provider_database_records(shared.COMPACT, provider_id)
    name_record = next((record for record in records if record.get('licenseNumber') == license_number), None)
    if name_record is None:
        name_record = next(record for record in records if record.get('type') == 'provider')
    return name_record['givenName'], name_record['familyName']


def _assert_license_eligibility_for_smoke_license(
    *,
    provider_id: str,
    license_number: str,
    expected_license_eligibility: str,
) -> None:
    """Public query by name; assert licenseEligibility for the smoke provider's matching license row."""
    given_name, family_name = _provider_name(provider_id, license_number)
    matching_license_rows = [
        row
        for row in call_public_query_providers(
            shared.COMPACT,
            first_name_filter=given_name,
            last_name_filter=family_name,
            provider_id_filter=provider_id,
            page_size=25,
        )
        if row.get('licenseNumber') == license_number
    ]
    if not matching_license_rows:
        raise SmokeTestFailureException(
            f'Public query returned no rows for provider {provider_id} (licenseNumber={license_number!r})'
        )
    license_row = matching_license_rows[0]
    actual_eligibility = license_row.get('licenseEligibility')
    if actual_eligibility != expected_license_eligibility:
        raise SmokeTestFailureException(
            f'Expected licenseEligibility {expected_license_eligibility!r} for provider {provider_id}, '
            f'got {actual_eligibility!r}'
        )


def test_public_lookup_does_not_match_against_old_license_records(provider_context: dict) -> None:
    """Insert an older license and verify public search does not return it."""
    table = get_provider_user_dynamodb_table()
    source_key = {'pk': provider_context['license_pk'], 'sk': provider_context['license_sk']}
    response = table.get_item(Key=source_key)

    clone = copy.deepcopy(response['Item'])
    license_type = clone['licenseType']
    license_type_abbr = get_license_type_abbreviation(license_type)

    clone['dateOfIssuance'] = shared.TEST_DATE_OF_ISSUANCE
    clone['dateOfRenewal'] = shared.TEST_DATE_OF_RENEWAL
    clone['licenseNumber'] = shared.TEST_LICENSE_NUMBER
    clone['jurisdiction'] = shared.TEST_JURISDICTION
    clone['sk'] = f'{shared.COMPACT}#PROVIDER#license/{shared.TEST_JURISDICTION}/{license_type_abbr}#'

    new_key: dict[str, str] | None = None
    try:
        table.put_item(Item=clone)
        new_key = {'pk': clone['pk'], 'sk': clone['sk']}
        wait_for_opensearch_sync()

        given_name, family_name = _provider_name(provider_context['provider_id'], provider_context['license_number'])
        matching_rows = [
            row
            for row in call_public_query_providers(
                shared.COMPACT,
                first_name_filter=given_name,
                last_name_filter=family_name,
                provider_id_filter=provider_context['provider_id'],
            )
            if row.get('licenseNumber') == shared.TEST_LICENSE_NUMBER
        ]
        if matching_rows:
            raise SmokeTestFailureException(
                f'Expected no public query rows for test license {shared.TEST_LICENSE_NUMBER!r}, got {matching_rows}'
            )

        public_provider_detail = call_public_get_provider(shared.COMPACT, provider_context['provider_id'])
        for lic in public_provider_detail.get('licenses'):
            if lic.get('licenseNumber') == shared.TEST_LICENSE_NUMBER:
                raise SmokeTestFailureException(f'Public GET unexpectedly included test license: {lic}')

        logger.info('Public search old license exclusion test passed')
    finally:
        if new_key is not None:
            logger.info(f'Deleting test license {new_key}')
            table.delete_item(Key=new_key)


if __name__ == '__main__':
    load_smoke_test_env()
    shared.COMPACT = 'psypact'
    shared.TEST_JURISDICTION = 'ne'
    shared._assert_license_eligibility_for_smoke_license = (  # noqa: SLF001
        _assert_license_eligibility_for_smoke_license
    )
    provider_context = shared.test_public_search_endpoints_returns_details_of_provider()
    shared.test_public_query_endpoint_returns_ineligible_license_if_license_is_expired(
        provider_context=provider_context
    )
    shared.test_public_query_endpoint_returns_ineligible_license_if_license_is_marked_by_jurisdiction_as_ineligible(
        provider_context=provider_context
    )
    test_public_lookup_does_not_match_against_old_license_records(provider_context=provider_context)
    logger.info('All public search smoke tests completed successfully.')
