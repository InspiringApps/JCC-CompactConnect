#!/usr/bin/env python3
# ruff: noqa: T201 we use print statements for local scripts
"""Bypass the Authorize.net credential requirement so a sandbox/test environment can be used to
test licensee registration end-to-end.

This script writes the minimum DynamoDB data needed so that:
  - The compact (diet) is marked as registration-enabled
  - The chosen state (default: NE) is marked as live
  - A fake paymentProcessorPublicFields stub is present so the frontend can
    render the registration form (no real Authorize.net credentials are stored)

Purchases will still fail (Secrets Manager has no real credential), but
registration itself will succeed because registration does NOT charge a card.

Run from backend/dietitian-app with appropriate AWS credentials:

    python bin/enable_registration_for_testing.py
    python bin/enable_registration_for_testing.py --jurisdiction ky
    python bin/enable_registration_for_testing.py --table-name my-override-table

Reads CC_TEST_COMPACT_CONFIGURATION_DYNAMO_TABLE_NAME from
tests/smoke/smoke_tests_env.json by default (same file used by other bin scripts).
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

APP_ROOT = Path(__file__).resolve().parent.parent
SMOKE_ENV_PATH = APP_ROOT / 'tests' / 'smoke' / 'smoke_tests_env.json'
COMPACT = 'diet'
COMPACT_NAME = 'Dietitian'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env() -> dict:
    if not SMOKE_ENV_PATH.exists():
        raise SystemExit(
            f'Missing {SMOKE_ENV_PATH}. '
            'Create it from smoke_tests_env_example.json or pass --table-name.'
        )
    with open(SMOKE_ENV_PATH) as fh:
        return json.load(fh)


def _pk_sk(compact: str) -> dict:
    key = f'{compact}#CONFIGURATION'
    return {'pk': key, 'sk': key}


def _jurisdiction_pk_sk(compact: str, jurisdiction: str) -> dict:
    return {'pk': f'{compact}#CONFIGURATION', 'sk': f'{compact}#JURISDICTION#{jurisdiction.lower()}'}


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _get_existing_compact_config(table, compact: str) -> dict | None:
    try:
        response = table.get_item(Key=_pk_sk(compact), ConsistentRead=True)
        return response.get('Item')
    except ClientError as exc:
        raise SystemExit(f'DynamoDB error reading compact config: {exc}') from exc


def _enable_compact_registration(table, compact: str, jurisdiction: str) -> None:
    """
    Upsert the compact configuration record so that:
      - licenseeRegistrationEnabled = True
      - the target jurisdiction is present in configuredStates with isLive = True
      - paymentProcessorPublicFields has stub values (satisfies the frontend
        form-render check; real credentials are NOT stored in Secrets Manager)
    """
    existing = _get_existing_compact_config(table, compact)

    if existing:
        # Merge: preserve every existing field, only patch what we need.
        configured_states: list[dict] = list(existing.get('configuredStates', []))

        # Ensure the target jurisdiction is present and live.
        found = False
        for state in configured_states:
            if state['postalAbbreviation'].lower() == jurisdiction.lower():
                if not state['isLive']:
                    print(f'  Marking {jurisdiction.upper()} as live in configuredStates ...')
                    state['isLive'] = True
                else:
                    print(f'  {jurisdiction.upper()} is already live in configuredStates.')
                found = True
                break
        if not found:
            print(f'  Adding {jurisdiction.upper()} to configuredStates with isLive=True ...')
            configured_states.append({'postalAbbreviation': jurisdiction.lower(), 'isLive': True})

        update_expression_parts = [
            'licenseeRegistrationEnabled = :lre',
            'configuredStates = :cs',
            'paymentProcessorPublicFields = :ppf',
            'dateOfUpdate = :dou',
        ]
        expression_attribute_values = {
            ':lre': True,
            ':cs': configured_states,
            ':ppf': {
                'apiLoginId': 'TEST-STUB-LOGIN-ID',
                'publicClientKey': 'TEST-STUB-PUBLIC-CLIENT-KEY',
            },
            ':dou': _now_iso(),
        }

        table.update_item(
            Key=_pk_sk(compact),
            UpdateExpression='SET ' + ', '.join(update_expression_parts),
            ExpressionAttributeValues=expression_attribute_values,
        )
        print(f'  Updated existing compact config for {compact}.')
    else:
        # No existing record — create a minimal one from scratch.
        print(f'  No existing compact config found. Creating new record for {compact} ...')
        item = {
            **_pk_sk(compact),
            'type': 'compact',
            'compactAbbr': compact,
            'compactName': COMPACT_NAME,
            'compactCommissionFee': {
                'feeType': 'FLAT_RATE',
                'feeAmount': Decimal('3.5'),
            },
            'compactOperationsTeamEmails': ['ops@example.com'],
            'compactAdverseActionsNotificationEmails': ['ops@example.com'],
            'compactSummaryReportNotificationEmails': ['ops@example.com'],
            'licenseeRegistrationEnabled': True,
            'configuredStates': [
                {'postalAbbreviation': jurisdiction.lower(), 'isLive': True},
            ],
            'paymentProcessorPublicFields': {
                'apiLoginId': 'TEST-STUB-LOGIN-ID',
                'publicClientKey': 'TEST-STUB-PUBLIC-CLIENT-KEY',
            },
            'dateOfUpdate': _now_iso(),
        }
        table.put_item(Item=item)
        print(f'  Created new compact config for {compact}.')


PRIVILEGE_FEE_AMOUNT = Decimal('10.00')


def _privilege_fees() -> list[dict]:
    """Dietitian has one license type. Amount must be Decimal — boto3 rejects floats."""
    return [
        {
            'licenseTypeAbbreviation': 'diet',
            'amount': PRIVILEGE_FEE_AMOUNT,
        },
    ]


def _has_expected_privilege_fee(fees: list | None) -> bool:
    return any(
        fee.get('licenseTypeAbbreviation') == 'diet' and fee.get('amount') == PRIVILEGE_FEE_AMOUNT
        for fee in fees or []
    )


def _ensure_jurisdiction_config(table, compact: str, jurisdiction: str) -> None:
    """
    Ensure a jurisdiction configuration record exists and passes JurisdictionRecordSchema.

    Registration loads this row and validates it. A record missing privilegeFees,
    jurisdictionSummaryReportNotificationEmails, or jurisprudenceRequirements raises
    ValidationError, which API Gateway surfaces as a 502.
    """
    key = _jurisdiction_pk_sk(compact, jurisdiction)
    response = table.get_item(Key=key, ConsistentRead=True)
    existing = response.get('Item')
    if existing:
        missing_fields = {}
        if not _has_expected_privilege_fee(existing.get('privilegeFees')):
            missing_fields['privilegeFees'] = _privilege_fees()
        if 'jurisdictionSummaryReportNotificationEmails' not in existing:
            missing_fields['jurisdictionSummaryReportNotificationEmails'] = []
        if not existing.get('jurisprudenceRequirements'):
            missing_fields['jurisprudenceRequirements'] = {'required': False}

        if not missing_fields:
            print(f'  Jurisdiction config for {jurisdiction.upper()} already exists — leaving as-is.')
            return

        print(
            f'  Jurisdiction config for {jurisdiction.upper()} needs '
            f'{", ".join(missing_fields)} — patching ...'
        )
        assignments = ', '.join(f'{name} = :{name}' for name in missing_fields)
        table.update_item(
            Key=key,
            UpdateExpression=f'SET {assignments}, dateOfUpdate = :dou',
            ExpressionAttributeValues={
                **{f':{name}': value for name, value in missing_fields.items()},
                ':dou': _now_iso(),
            },
        )
        print(f'  Patched jurisdiction config for {jurisdiction.upper()}.')
        return

    # Build jurisdiction name from abbreviation (best-effort readable name).
    state_names = {
        'al': 'Alabama', 'az': 'Arizona', 'co': 'Colorado', 'de': 'Delaware',
        'id': 'Idaho', 'ia': 'Iowa', 'ks': 'Kansas', 'ky': 'Kentucky',
        'me': 'Maine', 'md': 'Maryland', 'mn': 'Minnesota', 'ms': 'Mississippi',
        'mo': 'Missouri', 'mt': 'Montana', 'ne': 'Nebraska', 'nv': 'Nevada',
        'nh': 'New Hampshire', 'nd': 'North Dakota', 'oh': 'Ohio', 'ok': 'Oklahoma',
        'or': 'Oregon', 'pa': 'Pennsylvania', 'sd': 'South Dakota', 'tn': 'Tennessee',
        'tx': 'Texas', 'ut': 'Utah', 'va': 'Virginia', 'wa': 'Washington',
        'wv': 'West Virginia', 'wi': 'Wisconsin', 'wy': 'Wyoming',
    }
    jurisdiction_name = state_names.get(jurisdiction.lower(), jurisdiction.upper())

    item = {
        **key,
        'type': 'jurisdiction',
        'compact': compact,
        'postalAbbreviation': jurisdiction.lower(),
        'jurisdictionName': jurisdiction_name,
        'licenseeRegistrationEnabled': True,
        'jurisdictionOperationsTeamEmails': [],
        'jurisdictionAdverseActionsNotificationEmails': [],
        'jurisdictionSummaryReportNotificationEmails': [],
        'jurisprudenceRequirements': {'required': False},
        'privilegeFees': _privilege_fees(),
        'dateOfUpdate': _now_iso(),
    }
    table.put_item(Item=item)
    print(f'  Created jurisdiction config for {jurisdiction.upper()} ({jurisdiction_name}).')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = ArgumentParser(
        description=(
            'Patch DynamoDB so that licensee registration is unblocked for testing. '
            'No real Authorize.net credentials are stored — purchases will fail, '
            'but registration (which is free) will succeed.'
        ),
        epilog='Example: python bin/enable_registration_for_testing.py --jurisdiction ne',
    )
    parser.add_argument(
        '--jurisdiction',
        default='ne',
        metavar='POSTAL',
        help='State to mark live (default: ne). Must already be an active compact member in cdk.json.',
    )
    parser.add_argument(
        '--table-name',
        default=None,
        metavar='TABLE',
        help=(
            'DynamoDB compact configuration table name. '
            'Defaults to CC_TEST_COMPACT_CONFIGURATION_DYNAMO_TABLE_NAME from '
            'tests/smoke/smoke_tests_env.json.'
        ),
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print what would be written without actually writing to DynamoDB.',
    )
    args = parser.parse_args()

    jurisdiction = args.jurisdiction.lower()

    # Resolve table name.
    if args.table_name:
        table_name = args.table_name
    else:
        env = _load_env()
        table_name = env.get('CC_TEST_COMPACT_CONFIGURATION_DYNAMO_TABLE_NAME')
        if not table_name:
            raise SystemExit(
                'CC_TEST_COMPACT_CONFIGURATION_DYNAMO_TABLE_NAME not found in smoke_tests_env.json. '
                'Pass --table-name explicitly.'
            )

    print(f'\n\033[1;34mEnable Registration for Testing\033[0m')
    print(f'  Compact:       {COMPACT}')
    print(f'  Jurisdiction:  {jurisdiction.upper()}')
    print(f'  Table:         {table_name}')
    print(f'  Dry run:       {args.dry_run}\n')

    if args.dry_run:
        print('\033[1;33mDRY RUN — no changes written.\033[0m')
        print('Would write:')
        print(f'  compact config  pk/sk = {COMPACT}#CONFIGURATION')
        print(f'    licenseeRegistrationEnabled = True')
        print(f'    configuredStates[{jurisdiction}].isLive = True')
        print(f'    paymentProcessorPublicFields = stub values')
        print(f'  jurisdiction config pk = {COMPACT}#CONFIGURATION  sk = {COMPACT}#JURISDICTION#{jurisdiction}')
        print('    privilegeFees = [{licenseTypeAbbreviation: diet, amount: 10.00}]')
        print('    jurisdictionSummaryReportNotificationEmails = []')
        print('    jurisprudenceRequirements = {required: false}')
        sys.exit(0)

    dynamo = boto3.resource('dynamodb')
    table = dynamo.Table(table_name)

    print('Step 1: Compact configuration ...')
    _enable_compact_registration(table, COMPACT, jurisdiction)

    print('\nStep 2: Jurisdiction configuration ...')
    _ensure_jurisdiction_config(table, COMPACT, jurisdiction)

    print('\n\033[1;32mDone.\033[0m')
    print(
        f'\n{jurisdiction.upper()} is now live and registration is enabled for the {COMPACT_NAME} compact.\n'
        'The frontend should now allow a licensee to register.\n'
        '\033[1;33mNote:\033[0m Privilege purchases will still fail — no real Authorize.net '
        'credentials have been stored in Secrets Manager. That is expected for this test setup.\n'
    )


if __name__ == '__main__':
    main()
