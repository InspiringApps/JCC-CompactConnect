import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import boto3
from migrate import plan_migration

MAX_ROWS = 200
RDS_CA_BUNDLE_FILENAME = 'rds-global-bundle.pem'
_FETCH_SIZE = 500

APPROVAL_QUERY = """
SELECT a.UserId, u.Email AS Email, pt.InternalName AS authorizationType, ra.ApprovalDate,
       CONVERT(varchar(10), ra.ExpiryDate, 23) AS dateOfExpiration,
       state.Status AS renewalStatus
FROM [PsyPro.IA].dbo.RenewalActivity ra
JOIN [PsyPro.IA].dbo.Activity a ON a.ActivityId = ra.ActivityId
JOIN [PsyPro.IA].dbo.ProcessType pt ON pt.ProcessTypeId = ra.ProcessTypeId
JOIN [PsyPro.IA].dbo.[User] u ON u.UserId = a.UserId
LEFT JOIN [PsyPro.IA].dbo.RenewalProcessTypeState state
  ON state.RenewalId = a.UserId
 AND state.ProcessTypeId = ra.ProcessTypeId
WHERE ra.ApprovalDate IS NOT NULL
  AND ra.ExpiryDate IS NOT NULL
  AND ra.ProcessTypeId IN (11, 12)
  AND a.IsDeleted = 0
  AND u.IsDeleted = 0
"""

HOME_QUERY = """
SELECT ul.User_UserId AS UserId, j.Abbreviation
FROM [PsyPro.IA].dbo.UserLicenseJurisdictions ul
JOIN [PsyPro.IA].dbo.LicensureJurisdictions lj
  ON lj.LicenseJurisdictionId = ul.LicenseJurisdiction_LicenseJurisdictionId
JOIN [PsyPro.IA].dbo.Jurisdiction j
  ON j.JurisdictionId = lj.Jurisdiction_JurisdictionId
WHERE lj.IsHomeState = 1
"""


def query_psypro_source(event, _context):
    """Query the PSYPRO source database, or migrate approved records.

    Invoke a query with ``{"query": "SELECT ...", "max_rows": 50}``. Invoke the
    migration with ``{"action": "migrate"}``. Pass ``dryRun`` to plan the write
    without putting items. Row values are not written to the log.
    """
    if (event or {}).get('action') == 'migrate':
        return _migrate_approved_records(bool((event or {}).get('dryRun')))
    statement = (event or {}).get('query')
    if not isinstance(statement, str) or not statement.strip():
        raise ValueError('query is required')
    max_rows = _max_rows(event)
    secret = _database_secret()
    with _connect(secret) as connection:
        with connection.cursor() as cursor:
            cursor.execute(statement)
            if cursor.description is None:
                return {'rowCount': 0, 'rows': []}
            rows = [_json_row(row) for row in cursor.fetchmany(max_rows)]
    return {'rowCount': len(rows), 'rows': rows}


def _migrate_approved_records(dry_run: bool) -> dict:
    """Read approved APIT and TAP rows and write provider-table items."""
    secret = _database_secret()
    with _connect(secret) as connection:
        with connection.cursor() as cursor:
            cursor.execute(APPROVAL_QUERY)
            approval_rows = _fetch_all(cursor)
            cursor.execute(HOME_QUERY)
            home_rows = _fetch_all(cursor)
    prefix = os.environ['PSYPRO_TABLE_PREFIX']
    demographics = {
        int(item['userId']): item
        for item in _scan_table(f'{prefix}Demographics')
        if item.get('userId') is not None
    }
    licenses = _scan_table(f'{prefix}Licensures')
    emails = {int(row['UserId']): row['Email'] for row in approval_rows if row.get('Email')}
    planned = plan_migration(
        approval_rows=approval_rows,
        home_rows=home_rows,
        demographics=demographics,
        emails=emails,
        licenses=licenses,
        updated_at=datetime.now(UTC),
    )
    wrote = 0
    if not dry_run:
        _write_items(planned['items'])
        wrote = len(planned['items'])
    return {
        'dryRun': dry_run,
        'users': planned['users'],
        'authorizations': planned['authorizations'],
        'providers': planned['providers'],
        'licenses': planned['licenses'],
        'skippedProviders': planned['skippedProviders'],
        'skippedLicenses': planned['skippedLicenses'],
        'wrote': wrote,
    }


def _fetch_all(cursor) -> list[dict]:
    """Read every row. The migration does not use the ad hoc query cap."""
    if cursor.description is None:
        return []
    rows = []
    while True:
        batch = cursor.fetchmany(_FETCH_SIZE)
        if not batch:
            return rows
        rows.extend(_json_row(row) for row in batch)


def _scan_table(table_name: str) -> list[dict]:
    table = boto3.resource('dynamodb').Table(table_name)
    items = []
    response = table.scan()
    items.extend(_plain(item) for item in response.get('Items', []))
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(_plain(item) for item in response.get('Items', []))
    return items


def _write_items(items: list[dict]) -> None:
    table = boto3.resource('dynamodb').Table(os.environ['PROVIDER_TABLE_NAME'])
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)


def _plain(value):
    if isinstance(value, Decimal):
        if value == int(value):
            return int(value)
        return str(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _max_rows(event: dict) -> int:
    requested = (event or {}).get('max_rows', MAX_ROWS)
    try:
        requested = int(requested)
    except (TypeError, ValueError) as exc:
        raise ValueError('max_rows must be an integer') from exc
    if requested < 1:
        raise ValueError('max_rows must be at least 1')
    return min(requested, MAX_ROWS)


def _database_secret() -> dict:
    response = boto3.client('secretsmanager').get_secret_value(SecretId=os.environ['PSYPRO_SQL_SECRET_ARN'])
    return json.loads(response['SecretString'])


def _connect(secret: dict):
    import pytds

    database = secret.get('dbname') or 'master'
    return pytds.connect(
        server=secret.get('host') or os.environ['PSYPRO_SQL_HOST'],
        database=database,
        user=secret['username'],
        password=secret['password'],
        port=int(secret.get('port') or os.environ.get('PSYPRO_SQL_PORT') or 1433),
        timeout=60,
        login_timeout=30,
        as_dict=True,
        cafile=_certificate_bundle(),
    )


def _certificate_bundle() -> str:
    bundle = Path(__file__).with_name(RDS_CA_BUNDLE_FILENAME)
    if not bundle.is_file():
        raise FileNotFoundError(f'{RDS_CA_BUNDLE_FILENAME} was not packaged with this function')
    return str(bundle)


def _json_row(row: dict) -> dict:
    return {key: _json_value(value) for key, value in row.items()}


def _json_value(value):
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value
