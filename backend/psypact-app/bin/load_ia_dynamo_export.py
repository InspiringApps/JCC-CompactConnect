#!/usr/bin/env python3
"""
Load a DynamoDB JSON export into the IaSourceDataStack tables.

The export is the gzip DynamoDB JSON snapshot from
s3://asppb-ia-share-440342401730/DynamoDB/. Sync it locally first, then point
this script at that directory. Item bodies are not logged.

Example:
    aws s3 sync s3://asppb-ia-share-440342401730/DynamoDB/ ./ia-export --region us-east-1 \\
        --profile jcc-official-psypact-beta
    AWS_PROFILE=jcc-ia-psypact-test ./bin/load_ia_dynamo_export.py --export-dir ./ia-export
"""

import argparse
import gzip
import json
import logging
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

BATCH_SIZE = 25
logger = logging.getLogger(__name__)


def iter_data_files(table_dir: Path) -> list[Path]:
    """Return gzip data files for one exported table, ignoring manifest files."""
    patterns = (
        'AWSDynamoDB/*/data/*.json.gz',
        'data/*.json.gz',
        '*.json.gz',
    )
    for pattern in patterns:
        files = sorted(path for path in table_dir.glob(pattern) if 'manifest' not in path.name)
        if files:
            return files
    return []


def manifest_item_count(table_dir: Path) -> int | None:
    """Read itemCount from an AWS export manifest-summary, if one is present."""
    summaries = sorted(table_dir.glob('AWSDynamoDB/*/manifest-summary.json'))
    summaries.extend(sorted(table_dir.glob('manifest-summary.json')))
    if not summaries:
        return None
    summary = json.loads(summaries[0].read_text(encoding='utf-8'))
    item_count = summary.get('itemCount')
    return int(item_count) if item_count is not None else None


def iter_items(data_file: Path):
    """Yield DynamoDB attribute maps from one gzip JSON-lines file."""
    with gzip.open(data_file, 'rt', encoding='utf-8') as export_file:
        for line_number, line in enumerate(export_file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f'{data_file}:{line_number} is not valid JSON') from exc
            if isinstance(record, dict) and 'Item' in record:
                yield record['Item']
            elif isinstance(record, dict):
                yield record
            else:
                raise ValueError(f'{data_file}:{line_number} is not a DynamoDB item')


def write_batch(client, table_name: str, items: list[dict]) -> None:
    """Put one batch, retrying items DynamoDB returns as unprocessed."""
    request = {table_name: [{'PutRequest': {'Item': item}} for item in items]}
    for attempt in range(8):
        try:
            response = client.batch_write_item(RequestItems=request)
        except ClientError as exc:
            error_code = exc.response.get('Error', {}).get('Code', 'Unknown')
            raise RuntimeError(f'batch_write_item failed for {table_name}: {error_code}') from exc
        leftover = (response.get('UnprocessedItems') or {}).get(table_name) or []
        if not leftover:
            return
        request = {table_name: leftover}
        time.sleep(min(2**attempt, 30))
    raise RuntimeError(f'Unprocessed items remained for {table_name}')


def load_table(client, table_name: str, table_dir: Path) -> tuple[int, int | None]:
    """Write every item in one table export. Returns written count and manifest count."""
    pending: list[dict] = []
    written = 0
    for data_file in iter_data_files(table_dir):
        for item in iter_items(data_file):
            pending.append(item)
            if len(pending) == BATCH_SIZE:
                write_batch(client, table_name, pending)
                written += len(pending)
                pending = []
    if pending:
        write_batch(client, table_name, pending)
        written += len(pending)
    return written, manifest_item_count(table_dir)


def table_directories(export_dir: Path) -> list[Path]:
    """Each immediate child directory is one exported table."""
    return sorted(path for path in export_dir.iterdir() if path.is_dir() and not path.name.startswith('.'))


def load_export(export_dir: Path, region: str) -> int:
    """Load every table directory. Prints names and counts only."""
    client = boto3.client('dynamodb', region_name=region)
    failures = 0
    for table_dir in table_directories(export_dir):
        table_name = table_dir.name
        written, expected = load_table(client, table_name, table_dir)
        if expected is not None and written != expected:
            logger.error('%s: wrote %s, manifest itemCount %s', table_name, written, expected)
            failures += 1
        else:
            logger.info('%s: %s', table_name, written)
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Load a DynamoDB JSON export into IaSourceDataStack tables.')
    parser.add_argument('--export-dir', required=True, type=Path, help='Directory produced by aws s3 sync')
    parser.add_argument('--region', default='us-east-1')
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    args = parse_args()
    export_dir = args.export_dir
    if not export_dir.is_dir():
        raise SystemExit(f'Export directory does not exist: {export_dir}')
    failures = load_export(export_dir, args.region)
    if failures:
        raise SystemExit(f'{failures} table(s) did not match the export manifest')


if __name__ == '__main__':
    main()
