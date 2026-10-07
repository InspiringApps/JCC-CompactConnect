#!/usr/bin/env python3
# ruff: noqa: T201 we use print statements for local scripts
"""
Orchestrate privilege test-data generation across multiple compacts.

Prompts for a home state when one is not provided by querying licenseGSI for
eligible license counts in each active member jurisdiction (excluding the
privilege state), then invokes generate_privilege_test_data.py once per compact.

Run from 'backend/compact-connect' like:
bin/generate_multi_compact_privilege_test_data.py \\
    --compacts aslp octp coun --privilege-state ne --count 10

With a known home state (skips discovery):
bin/generate_multi_compact_privilege_test_data.py \\
    --compacts aslp octp --privilege-state ne --home-state oh --count 10
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config

with open('cdk.json') as context_file:
    _context = json.load(context_file)['context']
COMPACTS = _context['compacts']
ACTIVE_MEMBER_JURISDICTIONS = _context['active_compact_member_jurisdictions']

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATE_SCRIPT = os.path.join(SCRIPT_DIR, 'generate_privilege_test_data.py')


def count_eligible_licenses(
    provider_table,
    compact: str,
    home_state: str,
    license_type: str | None = None,
    license_uploaded_after: datetime | None = None,
) -> int:
    """Count eligible license records for a compact/home-state via licenseGSI or licenseUploadDateGSI."""
    from dateutil.relativedelta import relativedelta

    if license_uploaded_after:
        # licenseUploadDateGSI only projects providerId / keys, so eligibility and license-type
        # filters cannot be applied here. Count GSI hits as an availability signal for selection.
        current_date = datetime.now(tz=UTC)
        month_date = license_uploaded_after.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        total = 0

        while month_date <= current_date:
            year_month = month_date.strftime('%Y-%m')
            gsi_pk = f'C#{compact.lower()}#J#{home_state.lower()}#D#{year_month}'

            if month_date.year == license_uploaded_after.year and month_date.month == license_uploaded_after.month:
                upload_epoch_time = int(license_uploaded_after.timestamp())
            else:
                upload_epoch_time = int(month_date.timestamp())

            query_kwargs = {
                'IndexName': 'licenseUploadDateGSI',
                'KeyConditionExpression': Key('licenseUploadDateGSIPK').eq(gsi_pk)
                & Key('licenseUploadDateGSISK').gte(f'TIME#{upload_epoch_time}'),
                'Select': 'COUNT',
            }

            done = False
            start_key = None
            while not done:
                if start_key:
                    query_kwargs['ExclusiveStartKey'] = start_key
                response = provider_table.query(**query_kwargs)
                total += response.get('Count', 0)
                start_key = response.get('LastEvaluatedKey')
                done = start_key is None

            month_date = month_date + relativedelta(months=1)

        return total

    gsi_pk = f'C#{compact.lower()}#J#{home_state.lower()}'
    query_kwargs = {
        'IndexName': 'licenseGSI',
        'KeyConditionExpression': Key('licenseGSIPK').eq(gsi_pk),
        'FilterExpression': Attr('jurisdictionUploadedCompactEligibility').eq('eligible'),
        'Select': 'COUNT',
    }

    if license_type:
        query_kwargs['FilterExpression'] = query_kwargs['FilterExpression'] & Attr('licenseType').eq(license_type)

    total = 0
    done = False
    start_key = None

    while not done:
        if start_key:
            query_kwargs['ExclusiveStartKey'] = start_key

        response = provider_table.query(**query_kwargs)
        total += response.get('Count', 0)
        start_key = response.get('LastEvaluatedKey')
        done = start_key is None

    return total


def discover_home_state_counts(
    provider_table,
    compacts: list[str],
    privilege_state: str,
    license_type: str | None = None,
    license_uploaded_after: datetime | None = None,
) -> dict[str, dict[str, int]]:
    """
    Return {state: {compact: eligible_license_count}} for active member jurisdictions
    excluding the privilege state.
    """
    candidate_states: set[str] = set()
    for compact in compacts:
        for state in ACTIVE_MEMBER_JURISDICTIONS.get(compact, []):
            if state.lower() != privilege_state.lower():
                candidate_states.add(state.lower())

    counts: dict[str, dict[str, int]] = {}
    sorted_states = sorted(candidate_states)
    total_queries = len(sorted_states) * len(compacts)
    completed = 0

    print(
        f'\nScanning {len(sorted_states)} home states across {len(compacts)} compact(s) '
        f'for eligible licenses (excluding privilege state "{privilege_state}")...'
    )
    if license_uploaded_after:
        print(
            'Note: --license-uploaded-after counts are upload-date GSI hits '
            '(not yet filtered by eligibility/license type).'
        )

    for state in sorted_states:
        counts[state] = {}
        for compact in compacts:
            completed += 1
            member_states = {s.lower() for s in ACTIVE_MEMBER_JURISDICTIONS.get(compact, [])}
            if state not in member_states:
                counts[state][compact] = 0
                continue

            print(f'  [{completed}/{total_queries}] {compact}/{state}...', end=' ', flush=True)
            count = count_eligible_licenses(
                provider_table,
                compact,
                state,
                license_type,
                license_uploaded_after,
            )
            counts[state][compact] = count
            print(f'{count}')

    return counts


def prompt_home_state_selection(counts: dict[str, dict[str, int]], compacts: list[str], privilege_state: str) -> str:
    """Display eligible-license counts by home state and prompt the user to select one."""
    # Only show states with at least one eligible license in any requested compact
    states_with_data = [
        state for state, compact_counts in counts.items() if any(compact_counts.get(c, 0) > 0 for c in compacts)
    ]

    if not states_with_data:
        print('No eligible licenses found in any home state for the requested compact(s).')
        sys.exit(1)

    # Sort by total descending so the best options appear first
    states_with_data.sort(key=lambda s: sum(counts[s].get(c, 0) for c in compacts), reverse=True)

    col_width = max(8, max(len(c) for c in compacts) + 2)
    state_width = 8

    header = f'{"State":<{state_width}}' + ''.join(f'{c:<{col_width}}' for c in compacts) + f'{"Total":<8}'
    print(f'\nEligible license counts by home state (excluding "{privilege_state}"):')
    print(header)
    print('-' * len(header))

    for state in states_with_data:
        row_total = sum(counts[state].get(c, 0) for c in compacts)
        row = f'{state:<{state_width}}'
        row += ''.join(f'{counts[state].get(c, 0):<{col_width}}' for c in compacts)
        row += f'{row_total:<8}'
        print(row)

    print()
    while True:
        selected = input('Enter home state: ').strip().lower()
        if not selected:
            print('Home state is required.')
            continue
        if selected == privilege_state.lower():
            print(f'Home state cannot be the same as privilege state ({privilege_state}).')
            continue
        if selected not in counts:
            print(f'"{selected}" is not an active member jurisdiction for the requested compact(s).')
            continue
        if not any(counts[selected].get(c, 0) > 0 for c in compacts):
            print(f'No eligible licenses found in "{selected}". Pick a state from the list above.')
            continue
        return selected


def resolve_environment_and_table(environment: str | None, provider_table: str | None) -> tuple[str, str]:
    """Prompt for (or validate) environment name and provider table name."""
    print('\n⚠️  WARNING: This script will write directly to the database.')
    environment_name = environment or input('Enter the environment name (e.g., beta, sandbox, test): ').strip()
    if not environment_name:
        print('Error: Environment name is required')
        sys.exit(1)

    if environment_name.lower() in ('prod', 'production'):
        print('Error: This script cannot be run against production environments')
        sys.exit(1)

    provider_table_name = provider_table or input('Enter the full provider table name: ').strip()
    if not provider_table_name:
        print('Error: Provider table name is required')
        sys.exit(1)

    expected_prefix = f'{environment_name}-'
    if not provider_table_name.lower().startswith(expected_prefix.lower()):
        print(
            f'Error: Table name "{provider_table_name}" does not match environment "{environment_name}". '
            f'Expected table name to start with "{expected_prefix}" (case insensitive)'
        )
        sys.exit(1)

    print(f'✓ Validated table: {provider_table_name}')
    return environment_name, provider_table_name


def parse_license_uploaded_after(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError as e:
        print(f'Error: Invalid timestamp format for --license-uploaded-after: {e}')
        print('Expected ISO 8601 format (e.g., "2024-01-15T10:30:00Z" or "2024-01-15T10:30:00+00:00")')
        sys.exit(1)


def run_generate_for_compact(
    compact: str,
    home_state: str,
    privilege_state: str,
    environment: str,
    provider_table: str,
    count: int,
    license_type: str | None,
    license_uploaded_after: str | None,
) -> int:
    """Invoke generate_privilege_test_data.py for one compact. Returns the process exit code."""
    cmd = [
        sys.executable,
        GENERATE_SCRIPT,
        '--compact',
        compact,
        '--home-state',
        home_state,
        '--privilege-state',
        privilege_state,
        '--count',
        str(count),
        '--environment',
        environment,
        '--provider-table',
        provider_table,
    ]
    if license_type:
        cmd.extend(['--license-type', license_type])
    if license_uploaded_after:
        cmd.extend(['--license-uploaded-after', license_uploaded_after])

    print(f'\n{"=" * 60}')
    print(f'Running privilege generation for compact: {compact}')
    print(f'{"=" * 60}')
    print(f'Command: {" ".join(cmd)}\n')

    result = subprocess.run(cmd, check=False, cwd=os.path.dirname(SCRIPT_DIR) or '.')  # noqa: S603
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description='Generate privilege test data across multiple compacts, with optional home-state discovery'
    )
    parser.add_argument(
        '--compacts',
        nargs='+',
        required=True,
        choices=COMPACTS,
        help='One or more compacts to generate privileges for',
    )
    parser.add_argument('--privilege-state', required=True, help='Jurisdiction for privilege purchase')
    parser.add_argument(
        '--home-state',
        help='Jurisdiction where providers have licenses. If omitted, eligible states are listed for selection.',
    )
    parser.add_argument('--count', type=int, default=10, help='Number of privileges to generate per compact')
    parser.add_argument('--license-type', type=str, help='Optional: License type to associate with the privilege(s)')
    parser.add_argument(
        '--license-uploaded-after',
        type=str,
        help='Optional: UTC timestamp (ISO 8601) to only consider licenses uploaded after this time',
    )
    parser.add_argument('--environment', type=str, help='Optional: Environment name (skips interactive prompt)')
    parser.add_argument('--provider-table', type=str, help='Optional: Full provider table name (skips interactive prompt)')

    args = parser.parse_args()

    # Preserve order while deduplicating
    compacts = list(dict.fromkeys(args.compacts))
    privilege_state = args.privilege_state.lower()
    home_state = args.home_state.lower() if args.home_state else None

    if home_state and home_state == privilege_state:
        print('Error: home-state and privilege-state must be different')
        sys.exit(1)

    license_uploaded_after = parse_license_uploaded_after(args.license_uploaded_after)
    environment_name, provider_table_name = resolve_environment_and_table(args.environment, args.provider_table)

    if not home_state:
        dynamodb = boto3.resource('dynamodb', config=Config(retries={'max_attempts': 10}))
        provider_table = dynamodb.Table(provider_table_name)

        counts = discover_home_state_counts(
            provider_table,
            compacts,
            privilege_state,
            args.license_type,
            license_uploaded_after,
        )
        home_state = prompt_home_state_selection(counts, compacts, privilege_state)
        print(f'\nSelected home state: {home_state}')

    failures: list[str] = []
    for compact in compacts:
        exit_code = run_generate_for_compact(
            compact=compact,
            home_state=home_state,
            privilege_state=privilege_state,
            environment=environment_name,
            provider_table=provider_table_name,
            count=args.count,
            license_type=args.license_type,
            license_uploaded_after=args.license_uploaded_after,
        )
        if exit_code != 0:
            print(f'Warning: generate_privilege_test_data.py failed for compact "{compact}" (exit {exit_code})')
            failures.append(compact)

    print(f'\n{"=" * 60}')
    if failures:
        print(f'Completed with failures for: {", ".join(failures)}')
        print(f'Succeeded for: {", ".join(c for c in compacts if c not in failures) or "(none)"}')
        sys.exit(1)

    print(f'Successfully generated privileges for all compact(s): {", ".join(compacts)}')
    print(f'  home state: {home_state}')
    print(f'  privilege state: {privilege_state}')


if __name__ == '__main__':
    main()
