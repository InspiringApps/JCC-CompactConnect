import importlib.util
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

_LAMBDA_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_LAMBDA_DIR))
_HANDLER_PATH = _LAMBDA_DIR / 'handler.py'
_SPEC = importlib.util.spec_from_file_location('psypro_source_query_handler', _HANDLER_PATH)
handler = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(handler)


class TestPsyproSourceQuery(unittest.TestCase):
    def test_query_is_required(self):
        with self.assertRaises(ValueError):
            handler.query_psypro_source({}, None)

    def test_query_returns_json_rows(self):
        cursor = MagicMock()
        cursor.description = [('Status',)]
        cursor.fetchmany.return_value = [{'Status': 'Approved', 'When': date(2026, 1, 2), 'Count': Decimal('3')}]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        secret = {'username': 'admin', 'password': 'secret', 'host': 'db.example', 'port': 1433, 'dbname': 'master'}

        with (
            patch.object(handler, '_database_secret', return_value=secret),
            patch.object(handler, '_connect', return_value=connection),
        ):
            result = handler.query_psypro_source({'query': 'SELECT 1', 'max_rows': 10_000}, None)

        cursor.execute.assert_called_once_with('SELECT 1')
        cursor.fetchmany.assert_called_once_with(handler.MAX_ROWS)
        self.assertEqual(
            {'rowCount': 1, 'rows': [{'Status': 'Approved', 'When': '2026-01-02', 'Count': '3'}]},
            result,
        )

    def test_certificate_bundle_is_the_packaged_rds_file(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / handler.RDS_CA_BUNDLE_FILENAME
            bundle.write_text('-----BEGIN CERTIFICATE-----\n', encoding='utf-8')
            with patch.object(handler, '__file__', str(Path(directory) / 'handler.py')):
                self.assertEqual(str(bundle), handler._certificate_bundle())  # noqa: SLF001

    def test_migrate_writes_every_row_without_the_query_cap(self):
        approval_row = {
            'UserId': 7,
            'Email': 'ada@example.com',
            'authorizationType': 'APIT',
            'ApprovalDate': '2026-10-10T00:00:00',
            'dateOfExpiration': '2027-10-10',
            'renewalStatus': 0,
        }
        home_row = {'UserId': 7, 'Abbreviation': 'CO'}
        cursor = MagicMock()
        cursor.description = [('UserId',)]
        cursor.fetchmany.side_effect = [[approval_row], [], [home_row], []]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        secret = {'username': 'admin', 'password': 'secret', 'host': 'db.example', 'port': 1433}
        demographic = {
            'userId': 7,
            'firstName': 'Ada',
            'lastName': 'Lovelace',
            'birthDate': '1980-01-02',
            'ssn': '1234',
            'mailingAddress1': '1 Main St',
            'mailingCity': 'Denver',
            'mailingState': 'CO',
            'mailingZip': '80202',
        }

        license_row = {
            'userId': 7,
            'jurisdiction': 'CO',
            'licenseType': 'Doctoral Psychologist',
            'licensureNumber': 'PSY-1',
            'issueDate': '2019-05-01',
            'status': 'Active',
        }

        def scan(table_name):
            if table_name.endswith('Demographics'):
                return [demographic]
            if table_name.endswith('Licensures'):
                return [license_row]
            return []

        written = []
        with (
            patch.object(handler, '_database_secret', return_value=secret),
            patch.object(handler, '_connect', return_value=connection),
            patch.object(handler, '_scan_table', side_effect=scan),
            patch.object(handler, '_write_items', side_effect=written.extend),
            patch.dict(handler.os.environ, {'PSYPRO_TABLE_PREFIX': 'Psypro.'}, clear=False),
        ):
            result = handler.query_psypro_source({'action': 'migrate'}, None)

        executed = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual([handler.APPROVAL_QUERY, handler.HOME_QUERY], executed)
        self.assertFalse(result['dryRun'])
        self.assertEqual(3, result['wrote'])
        self.assertEqual(1, result['authorizations'])
        self.assertEqual(1, result['providers'])
        self.assertEqual(1, result['licenses'])
        authorization = next(item for item in written if item['type'] == 'authorization')
        self.assertEqual('psypact#MIGRATION#7', authorization['pk'])
        self.assertNotIn('providerId', authorization)
        self.assertEqual('Active', authorization['renewalStatus'])
        self.assertTrue(all('providerId' not in item for item in written))

    def test_migrate_dry_run_does_not_write(self):
        cursor = MagicMock()
        cursor.description = [('UserId',)]
        cursor.fetchmany.side_effect = [[], []]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        secret = {'username': 'admin', 'password': 'secret', 'host': 'db.example'}
        with (
            patch.object(handler, '_database_secret', return_value=secret),
            patch.object(handler, '_connect', return_value=connection),
            patch.object(handler, '_scan_table', return_value=[]),
            patch.object(handler, '_write_items') as write_items,
            patch.dict(handler.os.environ, {'PSYPRO_TABLE_PREFIX': 'Psypro.'}, clear=False),
        ):
            result = handler.query_psypro_source({'action': 'migrate', 'dryRun': True}, None)

        write_items.assert_not_called()
        self.assertTrue(result['dryRun'])
        self.assertEqual(0, result['wrote'])

    def test_missing_certificate_bundle_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(handler, '__file__', str(Path(directory) / 'handler.py')):
                with self.assertRaises(FileNotFoundError):
                    handler._certificate_bundle()  # noqa: SLF001
