#!/usr/bin/env python3
# ruff: noqa: T201 we use print statements for local scripts
"""Seed one billing month with initial uploads and renewals for an invoice test.

A license is billed as new when firstUploadDate falls in the month, and as a renewal
when firstUploadDate is earlier and dateOfRenewal falls in the month. The invoice
query only sees rows on licenseUploadDateGSI for that month: the license row for a
first upload, and a renewal license-update row for a renewal.

Renewals are given a first upload in a random earlier month (reproducible from --seed)
so September does not classify them as new.

    cd backend/cosmetology-app
    export AWS_PROFILE=jcc-cosmo-test
    python bin/seed_invoice_month.py --month 2026-09
    python bin/seed_invoice_month.py --month 2026-09 --delete

Re-running writes the same providers again. It does not add another 200.
"""

import argparse
import calendar
import hashlib
import json
import random
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

import boto3

# Stable ids so --delete removes the same rows a previous run wrote.
SEED_NAMESPACE = uuid.UUID('6f0c8e2a-1b4d-4e7a-9c3f-8a1d2e5b7c90')
SEED_MARKER = 'invoice-month-seed'
LICENSE_TYPE_ABBREVIATIONS = {
    'cosmetologist': 'cos',
    'esthetician': 'esth',
}
MONTH_PATTERN = re.compile(r'\d{4}-(0[1-9]|1[0-2])')
PRIOR_MONTH_WINDOW = 24


@dataclass(frozen=True)
class SeedLicense:
    category: str
    index: int
    provider_id: str
    first_upload: datetime
    renewal_on: datetime | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Seed compact-eligible licenses for one invoice month')
    parser.add_argument('--month', required=True, help='Billing month as YYYY-MM')
    parser.add_argument('--new', type=int, default=100, help='Initial uploads in the billing month (default 100)')
    parser.add_argument('--renewals', type=int, default=100, help='Renewals in the billing month (default 100)')
    parser.add_argument(
        '--license-type',
        default='esthetician',
        choices=sorted(LICENSE_TYPE_ABBREVIATIONS),
        help='License type to seed (default esthetician)',
    )
    parser.add_argument('--jurisdiction', help='Postal abbreviation. Defaults to the first configured jurisdiction.')
    parser.add_argument('--compact', help='Compact abbreviation. Defaults to the invoice Lambda COMPACTS value.')
    parser.add_argument('--seed', type=int, default=202609, help='RNG seed for prior upload months')
    parser.add_argument('--table-name', help='Provider table. Defaults to the invoice Lambda PROVIDER_TABLE_NAME.')
    parser.add_argument('--function-name', help='Invoice reporter Lambda used to discover table names.')
    parser.add_argument('--dry-run', action='store_true', help='Print the plan and write nothing')
    parser.add_argument('--delete', action='store_true', help='Delete the providers this script would write')
    return parser.parse_args()


def validate_month(month: str) -> str:
    if not MONTH_PATTERN.fullmatch(month):
        raise ValueError(f'--month must be YYYY-MM, got {month!r}')
    return month


def validate_counts(new_count: int, renewal_count: int) -> None:
    if new_count < 0 or renewal_count < 0:
        raise ValueError('--new and --renewals must be zero or greater')
    if new_count == 0 and renewal_count == 0:
        raise ValueError('Nothing to seed. Pass --new and/or --renewals.')


def find_invoice_function(lambda_client, explicit_name: str | None) -> dict:
    if explicit_name:
        return lambda_client.get_function_configuration(FunctionName=explicit_name)

    matches = []
    paginator = lambda_client.get_paginator('list_functions')
    for page in paginator.paginate():
        for function in page['Functions']:
            if 'InvoiceReporter' in function['FunctionName']:
                matches.append(function)

    if len(matches) == 1:
        return lambda_client.get_function_configuration(FunctionName=matches[0]['FunctionName'])
    if not matches:
        raise RuntimeError('No Lambda function name contains InvoiceReporter. Pass --function-name.')

    joined = '\n'.join(sorted(function['FunctionName'] for function in matches))
    raise RuntimeError(f'Multiple invoice reporter functions found. Pass --function-name.\n{joined}')


def lambda_env(function: dict) -> dict[str, str]:
    return function.get('Environment', {}).get('Variables', {})


def refuse_production(function: dict, table_name: str) -> None:
    environment_name = lambda_env(function).get('ENVIRONMENT_NAME', '')
    if environment_name.lower() == 'prod' or table_name.lower().startswith('prod'):
        raise RuntimeError(f'Refusing to seed production (environment={environment_name!r}, table={table_name!r})')


def configured_jurisdictions(dynamodb, compact: str, configuration_table_name: str) -> list[str]:
    table = dynamodb.Table(configuration_table_name)
    jurisdictions = []
    start_key = None
    while True:
        query = {
            'KeyConditionExpression': 'pk = :pk AND begins_with(sk, :sk)',
            'ExpressionAttributeValues': {
                ':pk': f'{compact}#CONFIGURATION',
                ':sk': f'{compact}#JURISDICTION#',
            },
            'ProjectionExpression': 'postalAbbreviation',
        }
        if start_key:
            query['ExclusiveStartKey'] = start_key
        response = table.query(**query)
        for item in response.get('Items', []):
            postal = item.get('postalAbbreviation')
            if postal:
                jurisdictions.append(str(postal).lower())
        start_key = response.get('LastEvaluatedKey')
        if not start_key:
            break
    return sorted(set(jurisdictions))


def months_before(billing_month: str, count: int) -> list[str]:
    year, month = (int(part) for part in billing_month.split('-'))
    months = []
    for _ in range(count):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append(f'{year:04d}-{month:02d}')
    return months


def timestamp_in_month(month: str, day: int) -> datetime:
    year, month_number = (int(part) for part in month.split('-'))
    last_day = calendar.monthrange(year, month_number)[1]
    return datetime(year, month_number, min(day, last_day), 12, 0, tzinfo=UTC)


def iso_z(value: datetime) -> str:
    return value.strftime('%Y-%m-%dT%H:%M:%SZ')


def provider_id_for(compact: str, jurisdiction: str, license_type: str, month: str, category: str, index: int) -> str:
    name = f'{compact}:{jurisdiction}:{license_type}:{month}:{category}:{index}'
    return str(uuid.uuid5(SEED_NAMESPACE, name))


def build_seeds(
    *,
    compact: str,
    jurisdiction: str,
    license_type: str,
    billing_month: str,
    new_count: int,
    renewal_count: int,
    seed: int,
) -> list[SeedLicense]:
    rng = random.Random(seed)
    prior_months = months_before(billing_month, PRIOR_MONTH_WINDOW)
    seeds = []

    for index in range(1, new_count + 1):
        seeds.append(
            SeedLicense(
                category='new',
                index=index,
                provider_id=provider_id_for(compact, jurisdiction, license_type, billing_month, 'new', index),
                first_upload=timestamp_in_month(billing_month, rng.randint(1, 28)),
                renewal_on=None,
            )
        )

    for index in range(1, renewal_count + 1):
        seeds.append(
            SeedLicense(
                category='renewal',
                index=index,
                provider_id=provider_id_for(compact, jurisdiction, license_type, billing_month, 'renewal', index),
                first_upload=timestamp_in_month(rng.choice(prior_months), rng.randint(1, 28)),
                renewal_on=timestamp_in_month(billing_month, rng.randint(1, 28)),
            )
        )

    return seeds


def gsi_pk(compact: str, jurisdiction: str, month: str) -> str:
    return f'C#{compact.lower()}#J#{jurisdiction.lower()}#D#{month}'


def gsi_sk(when: datetime, license_type_abbr: str, provider_id: str) -> str:
    return f'TIME#{int(when.timestamp())}#LT#{license_type_abbr}#PID#{provider_id}'


def address_fields(jurisdiction: str) -> dict:
    return {
        'homeAddressStreet1': '100 Seed Street',
        'homeAddressCity': 'Columbus',
        'homeAddressState': jurisdiction.upper(),
        'homeAddressPostalCode': '43215',
    }


def license_item(seed: SeedLicense, compact: str, jurisdiction: str, license_type: str) -> dict:
    license_type_abbr = LICENSE_TYPE_ABBREVIATIONS[license_type]
    family_name = f'Seed{seed.category}{seed.index:03d}'
    given_name = 'Invoice'
    license_prefix = 'EST' if license_type == 'esthetician' else 'COS'
    category_prefix = 'NEW' if seed.category == 'new' else 'REN'
    issued_on = seed.first_upload.date().isoformat()
    expires_on = f'{seed.first_upload.year + 2}-{seed.first_upload.strftime("%m-%d")}'
    updated_at = seed.renewal_on or seed.first_upload
    item = {
        'pk': f'{compact}#PROVIDER#{seed.provider_id}',
        'sk': f'{compact}#PROVIDER#license/{jurisdiction}/{license_type_abbr}#',
        'type': 'license',
        'seedMarker': SEED_MARKER,
        'providerId': seed.provider_id,
        'compact': compact,
        'jurisdiction': jurisdiction,
        'licenseType': license_type,
        'givenName': given_name,
        'familyName': family_name,
        'licenseNumber': f'{license_prefix}-{category_prefix}-{seed.index:04d}',
        'ssnLastFour': f'{seed.index % 10000:04d}',
        'dateOfBirth': '1990-06-15',
        'dateOfIssuance': issued_on,
        'dateOfExpiration': expires_on,
        'dateOfUpdate': iso_z(updated_at),
        'firstUploadDate': iso_z(seed.first_upload),
        'jurisdictionUploadedLicenseStatus': 'active',
        'jurisdictionUploadedCompactEligibility': 'eligible',
        'licenseGSIPK': f'C#{compact.lower()}#J#{jurisdiction.lower()}',
        'licenseGSISK': f'FN#{quote(family_name.lower())}#GN#{quote(given_name.lower())}',
        'licenseUploadDateGSIPK': gsi_pk(compact, jurisdiction, seed.first_upload.strftime('%Y-%m')),
        'licenseUploadDateGSISK': gsi_sk(seed.first_upload, license_type_abbr, seed.provider_id),
        **address_fields(jurisdiction),
    }
    if seed.renewal_on is not None:
        item['dateOfRenewal'] = seed.renewal_on.date().isoformat()
    return item


def provider_item(seed: SeedLicense, license_record: dict, compact: str, jurisdiction: str) -> dict:
    return {
        'pk': license_record['pk'],
        'sk': f'{compact}#PROVIDER',
        'type': 'provider',
        'seedMarker': SEED_MARKER,
        'providerId': seed.provider_id,
        'compact': compact,
        'licenseJurisdiction': jurisdiction,
        'givenName': license_record['givenName'],
        'familyName': license_record['familyName'],
        'ssnLastFour': license_record['ssnLastFour'],
        'dateOfBirth': license_record['dateOfBirth'],
        'birthMonthDay': '06-15',
        'dateOfExpiration': license_record['dateOfExpiration'],
        'dateOfUpdate': license_record['dateOfUpdate'],
        'providerDateOfUpdate': license_record['dateOfUpdate'],
        'providerFamGivMid': '#'.join(
            (
                quote(license_record['familyName'].lower()),
                quote(license_record['givenName'].lower()),
                '',
            )
        ),
        'jurisdictionUploadedLicenseStatus': 'active',
        'jurisdictionUploadedCompactEligibility': 'eligible',
    }


def renewal_update_item(
    seed: SeedLicense,
    license_record: dict,
    compact: str,
    jurisdiction: str,
    license_type: str,
) -> dict:
    license_type_abbr = LICENSE_TYPE_ABBREVIATIONS[license_type]
    created_at = seed.renewal_on
    if created_at is None:
        raise ValueError('Renewal update requires a renewal date')

    previous = {
        'licenseNumber': license_record['licenseNumber'],
        'ssnLastFour': license_record['ssnLastFour'],
        'givenName': license_record['givenName'],
        'familyName': license_record['familyName'],
        'dateOfUpdate': iso_z(seed.first_upload),
        'dateOfIssuance': license_record['dateOfIssuance'],
        'dateOfExpiration': license_record['dateOfExpiration'],
        'dateOfBirth': license_record['dateOfBirth'],
        'jurisdictionUploadedLicenseStatus': 'active',
        'jurisdictionUploadedCompactEligibility': 'eligible',
        **address_fields(jurisdiction),
    }
    change_hash = hashlib.sha256(seed.provider_id.encode()).hexdigest()[:16]
    create_iso = iso_z(created_at)
    return {
        'pk': license_record['pk'],
        'sk': (
            f'{compact}#UPDATE#3#license/{jurisdiction}/{license_type_abbr}/{create_iso}/{change_hash}'
        ),
        'type': 'licenseUpdate',
        'updateType': 'renewal',
        'seedMarker': SEED_MARKER,
        'providerId': seed.provider_id,
        'compact': compact,
        'jurisdiction': jurisdiction,
        'licenseType': license_type,
        'createDate': create_iso,
        'effectiveDate': create_iso,
        'dateOfUpdate': create_iso,
        'previous': previous,
        'updatedValues': {'dateOfRenewal': license_record['dateOfRenewal']},
        'licenseUploadDateGSIPK': gsi_pk(compact, jurisdiction, created_at.strftime('%Y-%m')),
        'licenseUploadDateGSISK': gsi_sk(created_at, license_type_abbr, seed.provider_id),
    }


def items_for_seed(seed: SeedLicense, compact: str, jurisdiction: str, license_type: str) -> list[dict]:
    license_record = license_item(seed, compact, jurisdiction, license_type)
    items = [provider_item(seed, license_record, compact, jurisdiction), license_record]
    if seed.category == 'renewal':
        items.append(renewal_update_item(seed, license_record, compact, jurisdiction, license_type))
    return items


def write_items(table, items: list[dict]) -> None:
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)


def delete_items(table, items: list[dict]) -> None:
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={'pk': item['pk'], 'sk': item['sk']})


def print_plan(seeds: list[SeedLicense], jurisdiction: str, license_type: str, billing_month: str) -> None:
    new_count = sum(1 for seed in seeds if seed.category == 'new')
    renewal_count = sum(1 for seed in seeds if seed.category == 'renewal')
    prior_months: dict[str, int] = {}
    for seed in seeds:
        if seed.category != 'renewal':
            continue
        month = seed.first_upload.strftime('%Y-%m')
        prior_months[month] = prior_months.get(month, 0) + 1

    print(f'{billing_month} {jurisdiction} {license_type}: {new_count} initial uploads, {renewal_count} renewals')
    print('Renewal first-upload months:')
    for month in sorted(prior_months):
        print(f'  {month}: {prior_months[month]}')


def main() -> None:
    args = parse_args()
    billing_month = validate_month(args.month)
    validate_counts(args.new, args.renewals)

    lambda_client = boto3.client('lambda')
    function = find_invoice_function(lambda_client, args.function_name)
    env = lambda_env(function)
    table_name = args.table_name or env.get('PROVIDER_TABLE_NAME')
    if not table_name:
        raise RuntimeError('Invoice Lambda has no PROVIDER_TABLE_NAME. Pass --table-name.')
    refuse_production(function, table_name)

    compacts = json.loads(env.get('COMPACTS', '[]'))
    compact = (args.compact or (compacts[0] if compacts else '')).lower()
    if not compact:
        raise RuntimeError('Invoice Lambda has no COMPACTS. Pass --compact.')

    configuration_table_name = env.get('COMPACT_CONFIGURATION_TABLE_NAME')
    dynamodb = boto3.resource('dynamodb')
    jurisdiction = (args.jurisdiction or '').lower()
    if not jurisdiction:
        if not configuration_table_name:
            raise RuntimeError('Pass --jurisdiction. Compact configuration table name was not found.')
        jurisdictions = configured_jurisdictions(dynamodb, compact, configuration_table_name)
        if not jurisdictions:
            raise RuntimeError(f'No jurisdictions configured for {compact}. Pass --jurisdiction.')
        jurisdiction = jurisdictions[0]
        print(f'Using jurisdiction {jurisdiction} (configured: {", ".join(jurisdictions)})')

    seeds = build_seeds(
        compact=compact,
        jurisdiction=jurisdiction,
        license_type=args.license_type,
        billing_month=billing_month,
        new_count=args.new,
        renewal_count=args.renewals,
        seed=args.seed,
    )
    items = [
        item
        for seed in seeds
        for item in items_for_seed(seed, compact, jurisdiction, args.license_type)
    ]
    print_plan(seeds, jurisdiction, args.license_type, billing_month)
    print(f'Table {table_name}: {len(items)} items')

    if args.dry_run:
        print('Dry run; nothing written.')
        return

    table = dynamodb.Table(table_name)
    if args.delete:
        delete_items(table, items)
        print(f'Deleted {len(seeds)} seeded providers from {table_name}')
        return

    write_items(table, items)
    print(f'Wrote {len(seeds)} seeded providers to {table_name}')
    print(
        'Invoice that month with: '
        f'python bin/generate_invoice_report.py --month {billing_month} --email you@example.com'
    )


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001 surface the CLI failure and exit
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
