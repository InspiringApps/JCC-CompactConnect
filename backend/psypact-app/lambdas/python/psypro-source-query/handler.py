import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import boto3

MAX_ROWS = 200
RDS_CA_BUNDLE_FILENAME = 'rds-global-bundle.pem'


def query_psypro_source(event, _context):
    """Run one SQL statement against the PSYPRO source database.

    Invoke with ``{"query": "SELECT ...", "max_rows": 50}``. The lambda can also
    read the Psypro.* DynamoDB tables named by PSYPRO_TABLE_PREFIX. Row values are
    returned to the caller and are not written to the log.
    """
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
