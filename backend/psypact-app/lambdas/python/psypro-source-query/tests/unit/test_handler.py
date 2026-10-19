import importlib.util
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

_HANDLER_PATH = Path(__file__).resolve().parents[2] / 'handler.py'
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
