#!/usr/bin/env python3
# ruff: noqa: T201 we use print statements for scripts run locally
"""Seed a dietitian sandbox or test account with live jurisdictions, licenses, and privileges.

This replaces the separate license-upload, provider-registration, privilege, and
registration-enablement scripts with one roster. Names, streets, and SSNs are fictional
but use real city ZIP codes and issued-looking SSN formats. License and login emails use
example.com so nothing is delivered to a real inbox.

Run from backend/dietitian-app. AWS credentials come from AWS_PROFILE, or from the
AWS_PROFILE value in tests/smoke/smoke_tests_env.json when that variable is unset.

    python3 bin/populate_dietitian_environment.py --dry-run
    python3 bin/populate_dietitian_environment.py

Registration stays usable without Authorize.net: the compact is marked live, each roster
state gets a jurisdiction row with a $10.00 dietitian privilege fee, and a stub
paymentProcessorPublicFields value is written only when the compact does not already
have one. Purchases still need real processor credentials.

Unregistered people have a license and no Cognito user, which is the registration-form
case. Privileges are only written for registered people.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import boto3
import requests
from botocore.exceptions import ClientError

APP_ROOT = Path(__file__).resolve().parent.parent
SMOKE_ENV_PATH = APP_ROOT / 'tests' / 'smoke' / 'smoke_tests_env.json'
COMMON_LIB = APP_ROOT / 'lambdas' / 'python' / 'common'
OUTPUT_PATH = APP_ROOT / 'tests' / 'smoke' / 'dietitian_population.json'
DEFAULT_PASSWORD = 'TestPass123!'  # noqa: S105 sandbox login password
PRIVILEGE_FEE = Decimal('10.00')
MILITARY_RATE = Decimal('8.00')
POLL_SECONDS = 5
WAIT_SECONDS = 180

JURISDICTION_NAMES = {
    'co': 'Colorado',
    'fl': 'Florida',
    'ga': 'Georgia',
    'ky': 'Kentucky',
    'mn': 'Minnesota',
    'nc': 'North Carolina',
    'ne': 'Nebraska',
    'oh': 'Ohio',
    'tx': 'Texas',
    'wa': 'Washington',
}


@dataclass(frozen=True)
class Persona:
    """One fictional licensee. registered people get a Cognito login. privileges are other states."""

    given_name: str
    middle_name: str
    family_name: str
    suffix: str | None
    jurisdiction: str
    ssn: str
    date_of_birth: str
    date_of_issuance: str
    date_of_renewal: str
    date_of_expiration: str
    street1: str
    street2: str | None
    city: str
    postal_code: str
    phone: str
    license_number: str
    npi_stem: str
    registered: bool
    privileges: tuple[str, ...]

    @property
    def email(self) -> str:
        given = self.given_name.lower()
        family = self.family_name.lower()
        return f'{given}.{family}@example.com'

    @property
    def display_name(self) -> str:
        suffix = f' {self.suffix}' if self.suffix else ''
        return f'{self.given_name} {self.middle_name} {self.family_name}{suffix}'


# Stable roster. Re-running uploads the same SSNs, so ingest updates these people instead of
# creating a second copy.
PERSONAS: tuple[Persona, ...] = (
    Persona(
        'Margaret',
        'Anne',
        'Chen',
        None,
        'ne',
        '505-62-1847',
        '1986-03-14',
        '2018-06-01',
        '2025-06-01',
        '2026-06-01',
        '2740 S 17th St',
        None,
        'Lincoln',
        '68502',
        '+14024763821',
        'RD-10482',
        '167384920',
        False,
        (),
    ),
    Persona(
        'James',
        'Robert',
        'Whitfield',
        None,
        'oh',
        '268-44-9021',
        '1979-11-02',
        '2014-09-15',
        '2025-09-15',
        '2026-09-15',
        '412 E Broad St',
        None,
        'Columbus',
        '43215',
        '+16143829410',
        'LD-22871',
        '158203746',
        False,
        (),
    ),
    Persona(
        'Priya',
        'Lakshmi',
        'Nandakumar',
        None,
        'ky',
        '400-71-3384',
        '1991-06-28',
        '2019-04-22',
        '2025-04-22',
        '2026-04-22',
        '815 E Market St',
        'Apt 4',
        'Louisville',
        '40202',
        '+15025581473',
        'DN-33019',
        '149572038',
        False,
        (),
    ),
    Persona(
        'Daniel',
        'Chinedu',
        'Okonkwo',
        None,
        'tx',
        '449-28-6615',
        '1984-01-19',
        '2016-02-11',
        '2026-02-11',
        '2027-02-11',
        '1901 S Congress Ave',
        None,
        'Austin',
        '78704',
        '+15124721958',
        'DT-77104',
        '136840295',
        False,
        (),
    ),
    Persona(
        'Elena',
        'Marie',
        'Vasquez',
        None,
        'co',
        '521-83-2290',
        '1993-09-07',
        '2021-08-03',
        '2025-08-03',
        '2026-08-03',
        '1550 Court Pl',
        None,
        'Denver',
        '80202',
        '+13038614720',
        'CD-55218',
        '124759063',
        False,
        (),
    ),
    Persona(
        'Hannah',
        'Grace',
        'Brooks',
        None,
        'wa',
        '531-19-7742',
        '1988-12-11',
        '2017-01-27',
        '2026-01-27',
        '2027-01-27',
        '2101 4th Ave',
        'Suite 300',
        'Seattle',
        '98121',
        '+12065590264',
        'WD-41883',
        '113684702',
        False,
        (),
    ),
    Persona(
        'Robert',
        'James',
        'Callahan',
        None,
        'nc',
        '237-55-4108',
        '1974-04-23',
        '2012-05-18',
        '2025-05-18',
        '2026-05-18',
        '227 Fayetteville St',
        None,
        'Raleigh',
        '27601',
        '+19198334617',
        'NC-RD-19044',
        '102573846',
        True,
        (),
    ),
    Persona(
        'Aisha',
        'Noor',
        'Rahman',
        None,
        'fl',
        '261-36-8824',
        '1982-08-16',
        '2015-11-09',
        '2025-11-09',
        '2026-11-09',
        '801 Brickell Ave',
        'Apt 1204',
        'Miami',
        '33131',
        '+13054127836',
        'FL-LD-66290',
        '198246573',
        True,
        (),
    ),
    Persona(
        'Thomas',
        'Minh',
        'Nguyen',
        None,
        'ga',
        '252-47-1193',
        '1990-02-05',
        '2018-07-30',
        '2025-07-30',
        '2026-07-30',
        '75 Ted Turner Dr SW',
        None,
        'Atlanta',
        '30303',
        '+14045591827',
        'GA-DT-28451',
        '187350214',
        True,
        (),
    ),
    Persona(
        'Claire',
        'Elizabeth',
        'Donovan',
        None,
        'mn',
        '468-22-5507',
        '1976-07-30',
        '2011-03-14',
        '2026-03-14',
        '2027-03-14',
        '800 LaSalle Ave',
        None,
        'Minneapolis',
        '55402',
        '+16123364785',
        'MN-RD-90317',
        '176249805',
        True,
        (),
    ),
    Persona(
        'Sarah',
        'Jane',
        'Lindgren',
        None,
        'ne',
        '505-81-6730',
        '1985-05-21',
        '2016-10-04',
        '2025-10-04',
        '2026-10-04',
        '1408 Farnam St',
        None,
        'Omaha',
        '68102',
        '+14025517384',
        'RD-22640',
        '165738420',
        True,
        ('oh', 'ky'),
    ),
    Persona(
        'Michael',
        'Tunde',
        'Adeyemi',
        None,
        'oh',
        '277-63-2048',
        '1981-10-09',
        '2013-12-02',
        '2025-12-02',
        '2026-12-02',
        '312 Walnut St',
        None,
        'Cincinnati',
        '45202',
        '+15136219047',
        'LD-81455',
        '154820367',
        True,
        ('ne', 'co'),
    ),
    Persona(
        'Jennifer',
        'Marie',
        'Kowalski',
        None,
        'ky',
        '401-15-9386',
        '1978-03-17',
        '2010-06-21',
        '2026-06-21',
        '2027-06-21',
        '401 W Main St',
        None,
        'Lexington',
        '40507',
        '+18592335816',
        'DN-14772',
        '143907658',
        True,
        ('ne', 'tx'),
    ),
    Persona(
        'David',
        'Raj',
        'Patel',
        None,
        'co',
        '522-90-4412',
        '1987-01-26',
        '2017-09-08',
        '2025-09-08',
        '2026-09-08',
        '201 S College Ave',
        None,
        'Fort Collins',
        '80524',
        '+19704826159',
        'CD-67033',
        '132086547',
        True,
        ('wa', 'oh'),
    ),
    Persona(
        'Lauren',
        'Michelle',
        'Mitchell',
        None,
        'tx',
        '453-38-7261',
        '1992-11-14',
        '2020-04-16',
        '2026-04-16',
        '2027-04-16',
        '1500 Marilla St',
        None,
        'Dallas',
        '75201',
        '+12147482563',
        'DT-39018',
        '121975834',
        True,
        ('ne', 'fl'),
    ),
    Persona(
        'Christopher',
        'Alan',
        'Hale',
        'Jr.',
        'wa',
        '532-64-1859',
        '1973-06-08',
        '2009-08-25',
        '2025-08-25',
        '2026-08-25',
        '747 Market St',
        None,
        'Tacoma',
        '98402',
        '+12535721490',
        'WD-55821',
        '110864723',
        True,
        ('ky', 'co'),
    ),
    Persona(
        'Rebecca',
        'Ruth',
        'Stein',
        None,
        'nc',
        '241-72-3095',
        '1989-09-03',
        '2019-02-19',
        '2026-02-19',
        '2027-02-19',
        '440 S Church St',
        None,
        'Charlotte',
        '28202',
        '+17043386921',
        'NC-RD-44108',
        '109753682',
        True,
        ('ga', 'oh'),
    ),
    Persona(
        'Andrew',
        'Luis',
        'Morales',
        None,
        'fl',
        '263-11-8476',
        '1980-12-22',
        '2014-01-13',
        '2026-01-13',
        '2027-01-13',
        '400 N Ashley Dr',
        None,
        'Tampa',
        '33602',
        '+18132296418',
        'FL-LD-77540',
        '198640257',
        True,
        ('tx', 'ne'),
    ),
)


def _load_cdk_context() -> dict:
    with open(APP_ROOT / 'cdk.json') as context_file:
        return json.load(context_file)['context']


def _load_smoke_env() -> dict:
    if not SMOKE_ENV_PATH.exists():
        raise SystemExit(f'Missing {SMOKE_ENV_PATH}. Copy smoke_tests_env_example.json and fill it in.')
    with open(SMOKE_ENV_PATH) as env_file:
        return json.load(env_file)


def _session(smoke_env: dict) -> boto3.Session:
    profile = os.environ.get('AWS_PROFILE') or smoke_env.get('AWS_PROFILE')
    region = os.environ.get('AWS_DEFAULT_REGION') or smoke_env.get('AWS_DEFAULT_REGION') or 'us-east-1'
    return boto3.Session(profile_name=profile, region_name=region)


def _prepare_schema_env(context: dict) -> None:
    os.environ['COMPACTS'] = json.dumps(context['compacts'])
    os.environ['JURISDICTIONS'] = json.dumps(context['jurisdictions'])
    os.environ['LICENSE_TYPES'] = json.dumps(context['license_types'])
    os.environ.setdefault('ENVIRONMENT_NAME', 'test')
    if str(COMMON_LIB) not in sys.path:
        sys.path.append(str(COMMON_LIB))


def _npi(stem: str) -> str:
    """CMS NPI check digit: Luhn over the 80840 prefix plus the nine-digit stem."""
    payload = '80840' + stem
    total = 0
    for index, character in enumerate(reversed(payload)):
        digit = int(character)
        if index % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    check = (10 - (total % 10)) % 10
    return f'{stem}{check}'


def _license_body(persona: Persona, license_type: str) -> dict:
    body = {
        'ssn': persona.ssn,
        'npi': _npi(persona.npi_stem),
        'licenseNumber': persona.license_number,
        'licenseType': license_type,
        'licenseStatus': 'active',
        'licenseStatusName': 'Active',
        'compactEligibility': 'eligible',
        'givenName': persona.given_name,
        'middleName': persona.middle_name,
        'familyName': persona.family_name,
        'dateOfIssuance': persona.date_of_issuance,
        'dateOfRenewal': persona.date_of_renewal,
        'dateOfExpiration': persona.date_of_expiration,
        'dateOfBirth': persona.date_of_birth,
        'homeAddressStreet1': persona.street1,
        'homeAddressCity': persona.city,
        'homeAddressState': persona.jurisdiction,
        'homeAddressPostalCode': persona.postal_code,
        'emailAddress': persona.email,
        'phoneNumber': persona.phone,
    }
    if persona.street2:
        body['homeAddressStreet2'] = persona.street2
    if persona.suffix:
        body['suffix'] = persona.suffix
    return body


def _validate_licenses(personas: tuple[Persona, ...], compact: str, license_type: str) -> None:
    from cc_common.data_model.schema.license.api import LicensePostRequestSchema
    from marshmallow import ValidationError

    schema = LicensePostRequestSchema()
    errors = {}
    for persona in personas:
        try:
            schema.load(
                {
                    **_license_body(persona, license_type),
                    'compact': compact,
                    'jurisdiction': persona.jurisdiction,
                }
            )
        except ValidationError as error:
            errors[persona.display_name] = error.messages
    if errors:
        raise SystemExit(f'Roster failed license schema validation: {json.dumps(errors, default=str)}')


def _roster_jurisdictions(personas: tuple[Persona, ...]) -> list[str]:
    states = {persona.jurisdiction for persona in personas}
    for persona in personas:
        states.update(persona.privileges)
    return sorted(states)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _ensure_compact(table, compact: str, jurisdictions: list[str], notify_email: str) -> None:
    key = {'pk': f'{compact}#CONFIGURATION', 'sk': f'{compact}#CONFIGURATION'}
    item = table.get_item(Key=key).get('Item') or {
        'pk': key['pk'],
        'sk': key['sk'],
        'type': 'compact',
        'compactAbbr': compact,
        'compactName': 'Dietitian',
        'compactCommissionFee': {'feeType': 'FLAT_RATE', 'feeAmount': Decimal('3.50')},
        'compactOperationsTeamEmails': [notify_email],
        'compactAdverseActionsNotificationEmails': [notify_email],
        'compactSummaryReportNotificationEmails': [notify_email],
        'configuredStates': [],
    }
    configured = {state['postalAbbreviation']: state for state in item.get('configuredStates', [])}
    for jurisdiction in jurisdictions:
        state = configured.get(jurisdiction, {'postalAbbreviation': jurisdiction})
        state['isLive'] = True
        configured[jurisdiction] = state
    item['configuredStates'] = [configured[abbreviation] for abbreviation in sorted(configured)]
    item['licenseeRegistrationEnabled'] = True
    if not item.get('paymentProcessorPublicFields'):
        item['paymentProcessorPublicFields'] = {
            'publicClientKey': '8a3c1e5b7d9f2a4c6e8b0d1f3a5c7e9b',
            'apiLoginId': '4wK7m2Qx9Lp',
        }
    item['dateOfUpdate'] = _now()
    table.put_item(Item=item)
    live = ', '.join(jurisdictions)
    print(f'Compact {compact} registration is on. Live states include {live}.')


def _diet_fee(fees: list[dict], license_abbr: str) -> list[dict]:
    kept = [fee for fee in fees if fee.get('licenseTypeAbbreviation') != license_abbr]
    current = next((fee for fee in fees if fee.get('licenseTypeAbbreviation') == license_abbr), None)
    if current is not None and Decimal(str(current.get('amount', '0'))) > 0:
        return fees
    kept.append(
        {
            'licenseTypeAbbreviation': license_abbr,
            'amount': PRIVILEGE_FEE,
            'militaryRate': MILITARY_RATE,
        }
    )
    return kept


def _ensure_jurisdictions(table, compact: str, jurisdictions: list[str], license_abbr: str, notify_email: str) -> None:
    for jurisdiction in jurisdictions:
        key = {'pk': f'{compact}#CONFIGURATION', 'sk': f'{compact}#JURISDICTION#{jurisdiction}'}
        item = table.get_item(Key=key).get('Item') or {
            'pk': key['pk'],
            'sk': key['sk'],
            'type': 'jurisdiction',
            'compact': compact,
            'postalAbbreviation': jurisdiction,
            'jurisdictionName': JURISDICTION_NAMES.get(jurisdiction, jurisdiction.upper()),
            'jurisdictionOperationsTeamEmails': [notify_email],
            'jurisdictionAdverseActionsNotificationEmails': [notify_email],
            'privilegeFees': [],
        }
        item['licenseeRegistrationEnabled'] = True
        item['privilegeFees'] = _diet_fee(item.get('privilegeFees', []), license_abbr)
        item.setdefault('jurisdictionSummaryReportNotificationEmails', [notify_email])
        item.setdefault('jurisprudenceRequirements', {'required': False})
        item['dateOfUpdate'] = _now()
        table.put_item(Item=item)
        print(f'  {jurisdiction} jurisdiction is live for registration')


def _create_app_client(cognito, pool_id: str, compact: str, jurisdiction: str) -> dict:
    response = cognito.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName=f'dietitian-populate-{jurisdiction}-{uuid.uuid4().hex[:8]}',
        PreventUserExistenceErrors='ENABLED',
        GenerateSecret=True,
        TokenValidityUnits={'AccessToken': 'minutes'},
        AccessTokenValidity=15,
        AllowedOAuthFlowsUserPoolClient=True,
        AllowedOAuthFlows=['client_credentials'],
        AllowedOAuthScopes=[f'{compact}/readGeneral', f'{jurisdiction}/{compact}.write'],
    )
    client = response['UserPoolClient']
    return {'client_id': client['ClientId'], 'client_secret': client['ClientSecret']}


def _delete_app_client(cognito, pool_id: str, client_id: str) -> None:
    try:
        cognito.delete_user_pool_client(UserPoolId=pool_id, ClientId=client_id)
    except ClientError as error:
        print(f'Warning: failed to delete temporary app client {client_id}: {error}', file=sys.stderr)


def _access_token(auth_url: str, client: dict, compact: str, jurisdiction: str) -> str:
    response = requests.post(
        auth_url,
        data={
            'grant_type': 'client_credentials',
            'client_id': client['client_id'],
            'client_secret': client['client_secret'],
            'scope': f'{compact}/readGeneral {jurisdiction}/{compact}.write',
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
        timeout=15,
    )
    if response.status_code != 200:
        raise SystemExit(f'Failed to get state-auth token for {jurisdiction} ({response.status_code}): {response.text}')
    token = response.json().get('access_token')
    if not token:
        raise SystemExit(f'State-auth response for {jurisdiction} had no access_token: {response.text}')
    return token


def _upload_jurisdiction(
    session: boto3.Session,
    smoke_env: dict,
    compact: str,
    jurisdiction: str,
    bodies: list[dict],
) -> None:
    cognito = session.client('cognito-idp')
    pool_id = smoke_env['CC_TEST_COGNITO_STATE_AUTH_USER_POOL_ID']
    client = _create_app_client(cognito, pool_id, compact, jurisdiction)
    try:
        token = _access_token(smoke_env['CC_TEST_STATE_AUTH_URL'], client, compact, jurisdiction)
        response = requests.post(
            f'{smoke_env["CC_TEST_STATE_API_BASE_URL"].rstrip("/")}/v1/compacts/{compact}/jurisdictions/{jurisdiction}/licenses',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json=bodies,
            timeout=60,
        )
        if response.status_code != 200:
            raise SystemExit(f'License upload for {jurisdiction} failed ({response.status_code}): {response.text}')
        print(f'Accepted {len(bodies)} {jurisdiction} license(s)')
    finally:
        _delete_app_client(cognito, pool_id, client['client_id'])


def _license_index_key(compact: str, persona: Persona) -> tuple[str, str]:
    partition = f'C#{compact.lower()}#J#{persona.jurisdiction.lower()}'
    sort = f'FN#{quote(persona.family_name.lower())}#GN#{quote(persona.given_name.lower())}'
    return partition, sort


def _find_provider_id(table, compact: str, persona: Persona) -> str | None:
    partition, sort = _license_index_key(compact, persona)
    response = table.query(
        IndexName='licenseGSI',
        KeyConditionExpression='licenseGSIPK = :pk AND licenseGSISK = :sk',
        ExpressionAttributeValues={':pk': partition, ':sk': sort},
    )
    for item in response.get('Items', []):
        if item.get('licenseNumber') == persona.license_number:
            return item.get('providerId')
    return None


def _wait_for_providers(table, compact: str, personas: tuple[Persona, ...]) -> dict[str, str]:
    pending = list(personas)
    found: dict[str, str] = {}
    deadline = time.monotonic() + WAIT_SECONDS
    while pending and time.monotonic() < deadline:
        still_pending = []
        for persona in pending:
            provider_id = _find_provider_id(table, compact, persona)
            if provider_id:
                found[persona.license_number] = provider_id
                print(f'  found {persona.display_name} {provider_id}')
            else:
                still_pending.append(persona)
        pending = still_pending
        if pending:
            time.sleep(POLL_SECONDS)
    if pending:
        missing = ', '.join(persona.display_name for persona in pending)
        raise SystemExit(f'License ingest did not finish for: {missing}')
    return found


def _attribute(user: dict, name: str) -> str | None:
    attributes = user.get('UserAttributes') or user.get('Attributes') or []
    return next((attribute['Value'] for attribute in attributes if attribute['Name'] == name), None)


def _register_provider(cognito, table, smoke_env: dict, compact: str, persona: Persona, provider_id: str) -> None:
    pool_id = smoke_env['CC_TEST_COGNITO_PROVIDER_USER_POOL_ID']
    try:
        cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=persona.email,
            UserAttributes=[
                {'Name': 'custom:compact', 'Value': compact},
                {'Name': 'custom:providerId', 'Value': provider_id},
                {'Name': 'email', 'Value': persona.email},
                {'Name': 'email_verified', 'Value': 'true'},
            ],
            MessageAction='SUPPRESS',
        )
    except ClientError as error:
        if error.response['Error']['Code'] != 'UsernameExistsException':
            message = error.response['Error']['Message']
            raise SystemExit(f'Failed to create Cognito user {persona.email}: {message}') from error
        existing = cognito.admin_get_user(UserPoolId=pool_id, Username=persona.email)
        bound_provider_id = _attribute(existing, 'custom:providerId')
        if bound_provider_id != provider_id:
            raise SystemExit(
                f'{persona.email} already exists and is bound to provider {bound_provider_id}, not {provider_id}.'
            ) from None
        print(f'  Cognito user {persona.email} already exists')

    try:
        cognito.admin_set_user_password(
            UserPoolId=pool_id,
            Username=persona.email,
            Password=DEFAULT_PASSWORD,
            Permanent=True,
        )
    except ClientError as error:
        raise SystemExit(f'Failed to set password for {persona.email}: {error.response["Error"]["Message"]}') from error

    table.update_item(
        Key={'pk': f'{compact}#PROVIDER#{provider_id}', 'sk': f'{compact}#PROVIDER'},
        UpdateExpression='SET compactConnectRegisteredEmailAddress = :email, currentHomeJurisdiction = :home',
        ExpressionAttributeValues={':email': persona.email, ':home': persona.jurisdiction},
    )


def _write_privileges(table, compact: str, persona: Persona, provider_id: str, license_abbr: str) -> None:
    if not persona.privileges:
        return
    issued = datetime.now(tz=UTC).isoformat()
    for jurisdiction in persona.privileges:
        transaction_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{persona.license_number}:{jurisdiction}'))
        table.put_item(
            Item={
                'pk': f'{compact}#PROVIDER#{provider_id}',
                'sk': f'{compact}#PROVIDER#privilege/{jurisdiction}/{license_abbr}#',
                'type': 'privilege',
                'providerId': provider_id,
                'compact': compact,
                'jurisdiction': jurisdiction,
                'licenseJurisdiction': persona.jurisdiction,
                'licenseType': 'dietitian',
                'dateOfIssuance': issued,
                'dateOfRenewal': issued,
                'dateOfExpiration': persona.date_of_expiration,
                'dateOfUpdate': issued,
                'compactTransactionId': transaction_id,
                'compactTransactionIdGSIPK': f'COMPACT#{compact}#TX#{transaction_id}#',
                'privilegeId': f'{license_abbr.upper()}-{jurisdiction.upper()}-{persona.license_number}',
                'administratorSetStatus': 'active',
                'attestations': [],
            }
        )
    table.update_item(
        Key={'pk': f'{compact}#PROVIDER#{provider_id}', 'sk': f'{compact}#PROVIDER'},
        UpdateExpression='ADD privilegeJurisdictions :states',
        ExpressionAttributeValues={':states': set(persona.privileges)},
    )


def _print_sheet(personas: tuple[Persona, ...], provider_ids: dict[str, str]) -> None:
    print()
    print(f'Registered logins use password {DEFAULT_PASSWORD}')
    print('On the registration form, use your own email. The license email is not an inbox.')
    print()
    for persona in personas:
        kind = 'registered' if persona.registered else 'unregistered'
        privileges = ', '.join(persona.privileges) if persona.privileges else 'none'
        provider_id = provider_ids.get(persona.license_number, '')
        print(f'{persona.display_name} ({kind})')
        print(f'  home: {persona.jurisdiction}  license: {persona.license_number}  provider: {provider_id}')
        print(f'  dob: {persona.date_of_birth}  ssn: {persona.ssn}  last four: {persona.ssn[-4:]}')
        street2 = f', {persona.street2}' if persona.street2 else ''
        print(f'  {persona.street1}{street2}, {persona.city} {persona.postal_code}  {persona.phone}')
        print(f'  privileges: {privileges}')
        if persona.registered:
            print(f'  login: {persona.email}')
        print()


def _check_roster(context: dict, compact: str) -> str:
    if compact not in context['compacts']:
        raise SystemExit(f'{compact} is not a compact in cdk.json')
    license_types = context['license_types'][compact]
    license_type = license_types[0]['name']
    license_abbr = license_types[0]['abbreviation']
    known = set(context['jurisdictions'])
    for persona in PERSONAS:
        if persona.jurisdiction not in known:
            raise SystemExit(f'{persona.display_name} home state {persona.jurisdiction} is not in cdk.json')
        if persona.jurisdiction in persona.privileges:
            raise SystemExit(f'{persona.display_name} has a privilege in their home state')
        unknown = [state for state in persona.privileges if state not in known]
        if unknown:
            raise SystemExit(f'{persona.display_name} has unknown privilege states: {", ".join(unknown)}')
        if persona.privileges and not persona.registered:
            raise SystemExit(f'{persona.display_name} has privileges without a registration')
    ssns = [persona.ssn for persona in PERSONAS]
    if len(ssns) != len(set(ssns)):
        raise SystemExit('Roster SSNs are not unique')
    _validate_licenses(PERSONAS, compact, license_type)
    return license_abbr


def main() -> None:
    parser = ArgumentParser(description='Populate dietitian jurisdictions, licenses, registrations, and privileges')
    parser.add_argument('--compact', default='diet')
    parser.add_argument('--dry-run', action='store_true', help='Validate the roster and print it. Do not call AWS.')
    args = parser.parse_args()

    context = _load_cdk_context()
    _prepare_schema_env(context)
    license_abbr = _check_roster(context, args.compact)
    jurisdictions = _roster_jurisdictions(PERSONAS)
    print(f'{len(PERSONAS)} people across {", ".join(jurisdictions)}')

    if args.dry_run:
        _print_sheet(PERSONAS, {})
        print('Dry run only. Nothing was written.')
        return

    smoke_env = _load_smoke_env()
    session = _session(smoke_env)
    notify_email = smoke_env.get('CC_TEST_SMOKE_TEST_NOTIFICATION_EMAIL') or 'dana@inspiringapps.com'
    config_table = session.resource('dynamodb').Table(smoke_env['CC_TEST_COMPACT_CONFIGURATION_DYNAMO_TABLE_NAME'])
    provider_table = session.resource('dynamodb').Table(smoke_env['CC_TEST_PROVIDER_DYNAMO_TABLE_NAME'])

    _ensure_compact(config_table, args.compact, jurisdictions, notify_email)
    _ensure_jurisdictions(config_table, args.compact, jurisdictions, license_abbr, notify_email)

    by_state: dict[str, list[Persona]] = {}
    for persona in PERSONAS:
        by_state.setdefault(persona.jurisdiction, []).append(persona)
    for jurisdiction, people in by_state.items():
        _upload_jurisdiction(
            session,
            smoke_env,
            args.compact,
            jurisdiction,
            [_license_body(persona, 'dietitian') for persona in people],
        )

    print('Waiting for license ingest...')
    provider_ids = _wait_for_providers(provider_table, args.compact, PERSONAS)
    cognito = session.client('cognito-idp')
    for persona in PERSONAS:
        provider_id = provider_ids[persona.license_number]
        if persona.registered:
            _register_provider(cognito, provider_table, smoke_env, args.compact, persona, provider_id)
        if persona.privileges:
            _write_privileges(provider_table, args.compact, persona, provider_id, license_abbr)

    summary = []
    for persona in PERSONAS:
        summary.append(
            {
                'name': persona.display_name,
                'registered': persona.registered,
                'email': persona.email if persona.registered else None,
                'password': DEFAULT_PASSWORD if persona.registered else None,
                'providerId': provider_ids[persona.license_number],
                'jurisdiction': persona.jurisdiction,
                'licenseNumber': persona.license_number,
                'ssn': persona.ssn,
                'ssnLastFour': persona.ssn[-4:],
                'dateOfBirth': persona.date_of_birth,
                'privileges': list(persona.privileges),
                'address': {
                    'street1': persona.street1,
                    'street2': persona.street2,
                    'city': persona.city,
                    'postalCode': persona.postal_code,
                },
                'phone': persona.phone,
            }
        )
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2))
    print(f'Wrote {OUTPUT_PATH}')
    _print_sheet(PERSONAS, provider_ids)


if __name__ == '__main__':
    main()
