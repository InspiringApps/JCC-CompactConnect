#!/usr/bin/env python3
"""Smoke tests for the PsyPact home-jurisdiction rule and generated privileges.

A home-jurisdiction change is accepted only when the selected state has an unexpired,
compact-eligible license. Privileges are not stored. A provider read builds them from the
most recently renewed or issued license, one per other live compact member.
"""

from datetime import UTC, datetime

import requests
from config import config, logger
from smoke_common import (
    SmokeTestFailureException,
    call_provider_users_me_endpoint,
    get_most_recently_issued_or_renewed_license,
    get_provider_user_auth_headers_cached,
    load_smoke_test_env,
)

# Live members from cdk.json active_compact_member_jurisdictions.psypact.
LIVE_JURISDICTIONS = ('co', 'ut')
# A jurisdiction the smoke provider is not expected to hold a license in.
REJECTED_JURISDICTION = 'oh'


def _license_is_valid_home(license_record: dict) -> bool:
    if license_record.get('compactEligibility') != 'eligible':
        return False
    expiration = license_record.get('dateOfExpiration')
    if not expiration:
        return False
    return datetime.fromisoformat(str(expiration)[:10]).date() >= datetime.now(UTC).date()


def _put_home_jurisdiction(jurisdiction: str):
    return requests.put(
        f'{config.api_base_url}/v1/provider-users/me/home-jurisdiction',
        headers=get_provider_user_auth_headers_cached(),
        json={'jurisdiction': jurisdiction},
        timeout=30,
    )


def test_home_jurisdiction_change_rejected_without_valid_license():
    """Changing home jurisdiction to a state without a valid license is rejected."""
    provider = call_provider_users_me_endpoint()
    valid_homes = {
        license_record['jurisdiction'].lower()
        for license_record in provider.get('licenses', [])
        if _license_is_valid_home(license_record)
    }
    if REJECTED_JURISDICTION in valid_homes:
        raise SmokeTestFailureException(
            f'Test provider already has a valid license in {REJECTED_JURISDICTION}. '
            'Use a jurisdiction they are not licensed in.'
        )

    response = _put_home_jurisdiction(REJECTED_JURISDICTION)
    if response.status_code != 400:
        raise SmokeTestFailureException(
            f'Expected 400 when changing home jurisdiction to {REJECTED_JURISDICTION} '
            f'without a valid license, got {response.status_code}: {response.text}'
        )
    logger.info('Home jurisdiction change without a valid license was rejected')


def test_home_jurisdiction_change_accepted_for_licensed_state():
    """A change to a state with a valid license succeeds and is recorded on the provider."""
    provider = call_provider_users_me_endpoint()
    valid_licenses = [
        license_record for license_record in provider.get('licenses', []) if _license_is_valid_home(license_record)
    ]
    if not valid_licenses:
        raise SmokeTestFailureException('Test provider has no unexpired compact-eligible license')

    original_home = (provider.get('currentHomeJurisdiction') or '').lower()
    target_license = next(
        (
            license_record
            for license_record in valid_licenses
            if license_record['jurisdiction'].lower() != original_home
        ),
        valid_licenses[0],
    )
    target_jurisdiction = target_license['jurisdiction'].lower()

    response = _put_home_jurisdiction(target_jurisdiction)
    if response.status_code != 200:
        raise SmokeTestFailureException(
            f'Expected 200 when setting home jurisdiction to {target_jurisdiction}, '
            f'got {response.status_code}: {response.text}'
        )

    try:
        updated = call_provider_users_me_endpoint()
        updated_home = (updated.get('currentHomeJurisdiction') or '').lower()
        if updated_home != target_jurisdiction:
            raise SmokeTestFailureException(
                f'currentHomeJurisdiction is {updated_home!r}, expected {target_jurisdiction!r}'
            )
        logger.info('Home jurisdiction updated to a state with a valid license')
    finally:
        if original_home and original_home != target_jurisdiction:
            restore = _put_home_jurisdiction(original_home)
            if restore.status_code != 200:
                logger.error(f'Failed to restore home jurisdiction to {original_home}: {restore.text}')


def test_privileges_are_generated_from_the_home_license():
    """Privileges on the provider read come from the latest license, not stored privilege rows."""
    provider = call_provider_users_me_endpoint()
    licenses = provider.get('licenses') or []
    if not licenses:
        raise SmokeTestFailureException('Test provider has no licenses')

    home_license = get_most_recently_issued_or_renewed_license(licenses)
    if home_license.get('compactEligibility') != 'eligible':
        raise SmokeTestFailureException(
            'The most recent license is not compact-eligible, so no privileges are generated. '
            f'License: {home_license.get("jurisdiction")} {home_license.get("licenseType")}'
        )

    home_jurisdiction = home_license['jurisdiction'].lower()
    privileges = provider.get('privileges') or []
    expected_jurisdictions = sorted(
        jurisdiction for jurisdiction in LIVE_JURISDICTIONS if jurisdiction != home_jurisdiction
    )
    actual_jurisdictions = sorted(privilege['jurisdiction'].lower() for privilege in privileges)
    if actual_jurisdictions != expected_jurisdictions:
        raise SmokeTestFailureException(
            'Generated privileges did not match live members other than the home license. '
            f'Expected {expected_jurisdictions}, got {actual_jurisdictions}'
        )

    for privilege in privileges:
        if privilege.get('licenseJurisdiction', '').lower() != home_jurisdiction:
            raise SmokeTestFailureException(
                f'Privilege in {privilege.get("jurisdiction")} has licenseJurisdiction '
                f'{privilege.get("licenseJurisdiction")!r}, expected {home_jurisdiction!r}'
            )
        if privilege.get('administratorSetStatus') != 'active':
            raise SmokeTestFailureException(
                f'Generated privilege administratorSetStatus is {privilege.get("administratorSetStatus")!r}'
            )
        if privilege.get('history'):
            raise SmokeTestFailureException(f'Generated privilege included history: {privilege.get("history")}')
        if privilege.get('compactTransactionId'):
            raise SmokeTestFailureException('Generated privilege includes a purchase transaction id')

    logger.info('Privileges were generated from the latest license for the other live members')


if __name__ == '__main__':
    load_smoke_test_env()
    test_home_jurisdiction_change_rejected_without_valid_license()
    test_home_jurisdiction_change_accepted_for_licensed_state()
    test_privileges_are_generated_from_the_home_license()
    logger.info('Home jurisdiction smoke tests passed')
