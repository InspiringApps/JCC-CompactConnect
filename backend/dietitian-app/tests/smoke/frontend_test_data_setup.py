# ruff: noqa: T201  print statements are intentional for developer output
#!/usr/bin/env python3
"""
frontend_test_data_setup.py

Seed the dietitian sandbox with provider test data for frontend registration and privilege testing.

Run from the backend/dietitian-app directory:
    python3 tests/smoke/frontend_test_data_setup.py           # create test data
    python3 tests/smoke/frontend_test_data_setup.py --cleanup # delete records from the previous run

What this script creates
------------------------
Three realistic provider states are seeded so the frontend dev can test every major flow:

  UNREGISTERED (3 providers)
    A license record exists in DynamoDB but no Cognito account has been claimed.
    The dev uses the printed SSN / DOB / name to drive the self-registration UI.

  REGISTERED, NO PRIVILEGES (2 providers)
    A Cognito account exists and the DynamoDB record carries
    compactConnectRegisteredEmailAddress + currentHomeJurisdiction, but the
    provider has not yet purchased any privileges.  The dev can log in with the
    printed email and password and verify the empty-privileges state.

  REGISTERED WITH PRIVILEGES (3 providers)
    Same as above, plus privilege records exist in DynamoDB across multiple
    jurisdictions.  The dev can log in and verify privilege display.

Note: unregistered + privileged is not a real-world state (privileges require
purchasing through the portal, which requires registration), so this script does
not create that combination.

Output
------
A "Frontend Dev Cheat Sheet" is printed and saved to
tests/smoke/frontend_test_data_ids.json for later cleanup.

Cleanup
-------
    python3 tests/smoke/frontend_test_data_setup.py --cleanup

Note: SSN table records cannot be deleted (by design), so those rows remain.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime

import boto3
import requests
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from config import config, logger
from smoke_common import (
    SmokeTestFailureException,
    create_test_app_client,
    create_test_privilege_record,
    delete_test_app_client,
    get_client_auth_headers,
    load_smoke_test_env,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPACT = 'diet'
LICENSE_TYPE = 'dietitian'
HOME_JURISDICTION = 'ne'  # Nebraska – home state for all test licenses

# Privilege jurisdictions for the "registered + privileged" group.
# Adjust as needed; ensure they are configured as live in the sandbox.
PRIVILEGE_JURISDICTIONS = ['ky', 'wa', 'co']

# Password shared by all registered test accounts (satisfies Cognito's default
# policy: >=8 chars, upper, lower, digit, special)
_TEST_PROVIDER_PASSWORD = 'FrontendTest1!'  # noqa: S105

# Temporary Cognito app client name (created and deleted each run)
_TEST_APP_CLIENT_NAME = 'frontend-test-data-setup-client'

# Saved IDs file – populated by setup, consumed by cleanup
_IDS_FILE = os.path.join(os.path.dirname(__file__), 'frontend_test_data_ids.json')

# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------
# Each dict is the authoritative definition of one test provider.
# "state" controls which DynamoDB / Cognito work is done for that provider:
#   "unregistered"            – license only; no Cognito account
#   "registered_no_priv"     – license + Cognito account; no privileges
#   "registered_with_priv"   – license + Cognito account + privilege records
#
# SSNs are in the 999-5x-xxxx range to avoid collisions with other smoke tests.

TEST_PROVIDERS = [
    # ── UNREGISTERED ───────────────────────────────────────────────────────
    {
        'state': 'unregistered',
        'givenName': 'Alice',
        'familyName': 'FrontendTest',
        'dateOfBirth': '1985-03-15',
        'ssn': '999-50-0001',
        'licenseNumber': 'DIET-FE-UNR-001',
        'homeAddressStreet1': '101 Elm Street',
        'homeAddressCity': 'Lincoln',
        'homeAddressPostalCode': '68501',
    },
    {
        'state': 'unregistered',
        'givenName': 'Bob',
        'familyName': 'FrontendTest',
        'dateOfBirth': '1990-07-22',
        'ssn': '999-50-0002',
        'licenseNumber': 'DIET-FE-UNR-002',
        'homeAddressStreet1': '202 Oak Avenue',
        'homeAddressCity': 'Omaha',
        'homeAddressPostalCode': '68102',
    },
    {
        'state': 'unregistered',
        'givenName': 'Carol',
        'familyName': 'FrontendTest',
        'dateOfBirth': '1978-11-30',
        'ssn': '999-50-0003',
        'licenseNumber': 'DIET-FE-UNR-003',
        'homeAddressStreet1': '303 Pine Lane',
        'homeAddressCity': 'Bellevue',
        'homeAddressPostalCode': '68005',
    },
    # ── REGISTERED – NO PRIVILEGES ─────────────────────────────────────────
    {
        'state': 'registered_no_priv',
        'givenName': 'Dave',
        'familyName': 'FrontendTest',
        'dateOfBirth': '1982-05-10',
        'ssn': '999-51-0001',
        'licenseNumber': 'DIET-FE-REG-001',
        'homeAddressStreet1': '404 Maple Drive',
        'homeAddressCity': 'Omaha',
        'homeAddressPostalCode': '68105',
        'email': 'dave.frontendtest@smokeTestFakeEmail.com',
    },
    {
        'state': 'registered_no_priv',
        'givenName': 'Eve',
        'familyName': 'FrontendTest',
        'dateOfBirth': '1993-09-18',
        'ssn': '999-51-0002',
        'licenseNumber': 'DIET-FE-REG-002',
        'homeAddressStreet1': '505 Cedar Road',
        'homeAddressCity': 'Lincoln',
        'homeAddressPostalCode': '68502',
        'email': 'eve.frontendtest@smokeTestFakeEmail.com',
    },
    # ── REGISTERED WITH PRIVILEGES ─────────────────────────────────────────
    {
        'state': 'registered_with_priv',
        'givenName': 'Frank',
        'familyName': 'FrontendTest',
        'dateOfBirth': '1975-01-25',
        'ssn': '999-52-0001',
        'licenseNumber': 'DIET-FE-PRV-001',
        'homeAddressStreet1': '606 Birch Boulevard',
        'homeAddressCity': 'Omaha',
        'homeAddressPostalCode': '68108',
        'email': 'frank.frontendtest@smokeTestFakeEmail.com',
        'privilegeJurisdictions': PRIVILEGE_JURISDICTIONS,
    },
    {
        'state': 'registered_with_priv',
        'givenName': 'Grace',
        'familyName': 'FrontendTest',
        'dateOfBirth': '1988-12-03',
        'ssn': '999-52-0002',
        'licenseNumber': 'DIET-FE-PRV-002',
        'homeAddressStreet1': '707 Walnut Way',
        'homeAddressCity': 'Bellevue',
        'homeAddressPostalCode': '68007',
        'email': 'grace.frontendtest@smokeTestFakeEmail.com',
        'privilegeJurisdictions': PRIVILEGE_JURISDICTIONS,
    },
    {
        'state': 'registered_with_priv',
        'givenName': 'Henry',
        'familyName': 'FrontendTest',
        'dateOfBirth': '1966-06-14',
        'ssn': '999-52-0003',
        'licenseNumber': 'DIET-FE-PRV-003',
        'homeAddressStreet1': '808 Spruce Court',
        'homeAddressCity': 'Lincoln',
        'homeAddressPostalCode': '68503',
        'email': 'henry.frontendtest@smokeTestFakeEmail.com',
        'privilegeJurisdictions': PRIVILEGE_JURISDICTIONS,
    },
]


# ---------------------------------------------------------------------------
# License upload helpers
# ---------------------------------------------------------------------------

def _build_license_body(provider: dict) -> list[dict]:
    return [
        {
            'licenseNumber': provider['licenseNumber'],
            'givenName': provider['givenName'],
            'familyName': provider['familyName'],
            'dateOfBirth': provider['dateOfBirth'],
            'ssn': provider['ssn'],
            'homeAddressStreet1': provider['homeAddressStreet1'],
            'homeAddressCity': provider['homeAddressCity'],
            'homeAddressState': HOME_JURISDICTION.upper(),
            'homeAddressPostalCode': provider['homeAddressPostalCode'],
            'licenseType': LICENSE_TYPE,
            'dateOfIssuance': '2022-01-01',
            'dateOfExpiration': '2050-12-31',
            'licenseStatus': 'active',
            'compactEligibility': 'eligible',
        }
    ]


def _post_license(client_id: str, client_secret: str, provider: dict) -> None:
    headers = get_client_auth_headers(client_id, client_secret, COMPACT, HOME_JURISDICTION)
    url = f'{config.state_api_base_url}/v1/compacts/{COMPACT}/jurisdictions/{HOME_JURISDICTION}/licenses'
    response = requests.post(url=url, headers=headers, json=_build_license_body(provider), timeout=60)
    if response.status_code != 200:
        raise SmokeTestFailureException(
            f"Failed to upload license for {provider['givenName']} {provider['familyName']}: {response.json()}"
        )
    logger.info(f"License uploaded for {provider['givenName']} {provider['familyName']}")


def _wait_for_provider_by_license_number(
    license_number: str,
    given_name: str,
    family_name: str,
    max_wait_seconds: int = 360,
    poll_interval: int = 30,
) -> str:
    """Poll the provider DynamoDB table directly for a license record with the given license number.

    This avoids the staff Cognito user entirely, so it works against environments that have
    Cognito Advanced Security Mode enabled (i.e. non-VULNERABLE deployments like jcc-diet-test).
    Returns the provider UUID extracted from the license record's partition key.
    """
    table = config.provider_user_dynamodb_table
    max_attempts = max_wait_seconds // poll_interval

    for attempt in range(1, max_attempts + 1):
        response = table.scan(
            FilterExpression='licenseNumber = :ln AND #t = :t',
            ExpressionAttributeNames={'#t': 'type'},
            ExpressionAttributeValues={':ln': license_number, ':t': 'license'},
        )
        items = response.get('Items', [])
        if items:
            # pk format: diet#PROVIDER#{uuid}
            provider_id = items[0]['pk'].split('#PROVIDER#')[1]
            logger.info(f'Found {given_name} {family_name} → provider {provider_id} (attempt {attempt})')
            return provider_id

        if attempt < max_attempts:
            logger.info(
                f'{given_name} {family_name} not yet in DynamoDB '
                f'(attempt {attempt}/{max_attempts}), waiting {poll_interval}s…'
            )
            time.sleep(poll_interval)

    raise SmokeTestFailureException(
        f'Timed out waiting for license {license_number} ({given_name} {family_name}) '
        f'after {max_wait_seconds}s'
    )


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def _create_provider_cognito_user(provider_id: str, email: str) -> None:
    """Create and activate a Cognito provider user, mirroring what the registration endpoint does."""
    cognito = boto3.client('cognito-idp')
    pool_id = config.cognito_provider_user_pool_id

    try:
        cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            MessageAction='SUPPRESS',   # don't email a fake address
            UserAttributes=[
                {'Name': 'custom:compact', 'Value': COMPACT},
                {'Name': 'custom:providerId', 'Value': str(provider_id)},
                {'Name': 'email', 'Value': email},
                {'Name': 'email_verified', 'Value': 'true'},
            ],
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'UsernameExistsException':
            logger.info(f'Cognito user {email} already exists, skipping creation')
        else:
            raise SmokeTestFailureException(f'Failed to create Cognito user {email}: {e}') from e

    # Set a permanent password so the dev can log in immediately
    cognito.admin_set_user_password(
        UserPoolId=pool_id,
        Username=email,
        Password=_TEST_PROVIDER_PASSWORD,
        Permanent=True,
    )
    logger.info(f'Cognito provider user created and activated: {email}')


def _register_provider_in_dynamo(provider_id: str, email: str) -> None:
    """Update the top-level provider DynamoDB record with the registration fields."""
    table = config.provider_user_dynamodb_table
    table.update_item(
        Key={
            'pk': f'{COMPACT}#PROVIDER#{provider_id}',
            'sk': f'{COMPACT}#PROVIDER',
        },
        UpdateExpression=(
            'SET compactConnectRegisteredEmailAddress = :email, '
            'currentHomeJurisdiction = :jurisdiction'
        ),
        ExpressionAttributeValues={
            ':email': email,
            ':jurisdiction': HOME_JURISDICTION,
        },
    )
    logger.info(f'Set registration fields on DynamoDB record for provider {provider_id}')


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------

def _delete_all_provider_dynamo_records(provider_id: str) -> None:
    table = config.provider_user_dynamodb_table
    items = table.query(
        KeyConditionExpression=Key('pk').eq(f'{COMPACT}#PROVIDER#{provider_id}')
    ).get('Items', [])
    for item in items:
        table.delete_item(Key={'pk': item['pk'], 'sk': item['sk']})
    logger.info(f'Deleted {len(items)} DynamoDB records for provider {provider_id}')


def _delete_provider_cognito_user(email: str) -> None:
    cognito = boto3.client('cognito-idp')
    try:
        cognito.admin_delete_user(
            UserPoolId=config.cognito_provider_user_pool_id,
            Username=email,
        )
        logger.info(f'Deleted Cognito provider user: {email}')
    except ClientError as e:
        if e.response['Error']['Code'] == 'UserNotFoundException':
            logger.info(f'Cognito user {email} not found, skipping deletion')
        else:
            logger.warning(f'Failed to delete Cognito user {email}: {e}')


def run_cleanup() -> None:
    if not os.path.exists(_IDS_FILE):
        print(f'No saved ID file found at {_IDS_FILE}. Nothing to clean up.')
        return

    with open(_IDS_FILE) as f:
        saved = json.load(f)

    providers = saved.get('providers', [])
    if not providers:
        print('No providers in saved file. Nothing to clean up.')
        return

    print(f'Cleaning up {len(providers)} provider(s)…')
    for entry in providers:
        provider_id = entry.get('providerId')
        email = entry.get('email')
        if provider_id:
            _delete_all_provider_dynamo_records(provider_id)
        if email:
            _delete_provider_cognito_user(email)

    os.remove(_IDS_FILE)
    print('Cleanup complete. (SSN table rows are permanent and were not deleted.)')


# ---------------------------------------------------------------------------
# Main setup flow
# ---------------------------------------------------------------------------

def run_setup() -> None:
    client_id = None
    results: list[dict] = []

    try:
        # 1. Temporary Cognito app client (for state-API license uploads)
        credentials = create_test_app_client(_TEST_APP_CLIENT_NAME, COMPACT, HOME_JURISDICTION)
        client_id = credentials['client_id']
        client_secret = credentials['client_secret']

        # 2. Upload all license records
        print(f'\nUploading {len(TEST_PROVIDERS)} license records via state API…')
        for provider in TEST_PROVIDERS:
            _post_license(client_id, client_secret, provider)

        # 3. Wait for each provider to appear in DynamoDB (SQS ingest pipeline).
        #    Polls DynamoDB directly — no Cognito staff user required.
        print('\nWaiting for the license ingest pipeline (this may take a few minutes)…')
        for provider in TEST_PROVIDERS:
            provider_id = _wait_for_provider_by_license_number(
                license_number=provider['licenseNumber'],
                given_name=provider['givenName'],
                family_name=provider['familyName'],
            )
            results.append({**provider, 'providerId': provider_id})

        # 4. Register and/or add privileges depending on each provider's target state
        print('\nApplying registration and privilege records…')
        for entry in results:
            provider_id = entry['providerId']
            state = entry['state']
            email = entry.get('email')

            if state in ('registered_no_priv', 'registered_with_priv'):
                _create_provider_cognito_user(provider_id, email)
                _register_provider_in_dynamo(provider_id, email)

            if state == 'registered_with_priv':
                for jurisdiction in entry.get('privilegeJurisdictions', PRIVILEGE_JURISDICTIONS):
                    create_test_privilege_record(
                        provider_id=provider_id,
                        compact=COMPACT,
                        jurisdiction=jurisdiction,
                        license_jurisdiction=HOME_JURISDICTION,
                        license_type=LICENSE_TYPE,
                    )

            logger.info(f"State '{state}' applied for {entry['givenName']} {entry['familyName']}")

    finally:
        # Always clean up the temporary Cognito app client
        if client_id:
            delete_test_app_client(client_id)

    # 6. Save IDs and print cheat sheet
    saved = {'createdAt': datetime.now(tz=UTC).isoformat(), 'providers': results}
    with open(_IDS_FILE, 'w') as f:
        json.dump(saved, f, indent=2)

    _print_cheat_sheet(results)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _print_cheat_sheet(results: list[dict]) -> None:
    sep = '=' * 72
    thin = '─' * 56

    # Group by state for a cleaner layout
    groups = {
        'unregistered': ('UNREGISTERED (no Cognito account)', []),
        'registered_no_priv': ('REGISTERED – NO PRIVILEGES', []),
        'registered_with_priv': ('REGISTERED WITH PRIVILEGES', []),
    }
    for entry in results:
        groups[entry['state']][1].append(entry)

    print(f'\n{sep}')
    print('  FRONTEND DEV CHEAT SHEET  –  Dietitian Sandbox Test Data')
    print(f'{sep}\n')

    for state_key, (title, entries) in groups.items():
        if not entries:
            continue

        print(f'  ┌─ {title} ({len(entries)} provider(s))')
        for entry in entries:
            print(f'  │')
            print(f'  │  Provider ID  : {entry["providerId"]}')
            if state_key == 'unregistered':
                print(f'  │  ── Registration form data ──')
                print(f'  │  Given Name      : {entry["givenName"]}')
                print(f'  │  Family Name     : {entry["familyName"]}')
                print(f'  │  Date of Birth   : {entry["dateOfBirth"]}')
                print(f'  │  SSN (last 4)    : {entry["ssn"].split("-")[-1]}')
                print(f'  │  License #       : {entry["licenseNumber"]}')
                print(f'  │  Compact         : {COMPACT}')
                print(f'  │  License Type    : {LICENSE_TYPE}')
                print(f'  │  Jurisdiction    : {HOME_JURISDICTION.upper()}')
            else:
                print(f'  │  ── Login credentials ──')
                print(f'  │  Email    : {entry["email"]}')
                print(f'  │  Password : {_TEST_PROVIDER_PASSWORD}')
                if state_key == 'registered_with_priv':
                    privs = entry.get('privilegeJurisdictions', PRIVILEGE_JURISDICTIONS)
                    print(f'  │  ── Privileges ──')
                    for j in privs:
                        print(f'  │    • {j.upper()} ({LICENSE_TYPE})')
        print(f'  └─{thin}')
        print()

    print(f'{sep}')
    print(f'  Login password for all registered accounts: {_TEST_PROVIDER_PASSWORD}')
    print(f'  Saved IDs: {_IDS_FILE}')
    print(f'  Cleanup:   python3 tests/smoke/frontend_test_data_setup.py --cleanup')
    print(f'{sep}\n')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Delete all provider records and Cognito users from the previous run.',
    )
    args = parser.parse_args()

    load_smoke_test_env()

    if args.cleanup:
        run_cleanup()
    else:
        run_setup()
