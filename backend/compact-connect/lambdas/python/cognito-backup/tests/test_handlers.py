"""
Unit tests for the Cognito backup handlers.

This module tests the handler functions and classes in isolation
using mock objects rather than actual AWS services.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from tests import TstLambdas


class TestCognitoBackupExporter(TstLambdas):
    """Unit tests for the CognitoBackupExporter class."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

    @patch('handlers.cognito_backup.boto3.client')
    def test_init(self, mock_boto3_client):
        """Test CognitoBackupExporter initialization."""
        from handlers.cognito_backup import CognitoBackupExporter

        exporter = CognitoBackupExporter('us-east-1_testpool', 'test-backup-bucket', 'staff')

        # Verify boto3 clients are created
        self.assertEqual(mock_boto3_client.call_count, 2)
        mock_boto3_client.assert_any_call('cognito-idp')
        mock_boto3_client.assert_any_call('s3')

        # Verify parameters are set correctly
        self.assertEqual(exporter.user_pool_id, 'us-east-1_testpool')
        self.assertEqual(exporter.backup_bucket_name, 'test-backup-bucket')
        self.assertEqual(exporter.user_pool_type, 'staff')

    @patch('handlers.cognito_backup.boto3.client')
    def test_extract_user_attributes(self, mock_boto3_client):
        """Test user attributes extraction."""
        from handlers.cognito_backup import CognitoBackupExporter

        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]

        attributes = [
            {'Name': 'email', 'Value': 'test@example.com'},
            {'Name': 'given_name', 'Value': 'Test'},
            {'Name': 'family_name', 'Value': 'User'},
            {'Name': 'custom:providerId', 'Value': 'prov123'},
        ]

        exporter = CognitoBackupExporter('us-east-1_testpool', 'test-bucket', 'staff')
        result = exporter._extract_user_attributes(attributes)  # noqa: SLF001 testing private method

        expected = {
            'email': 'test@example.com',
            'given_name': 'Test',
            'family_name': 'User',
            'custom:providerId': 'prov123',
        }
        self.assertEqual(result, expected)

    @patch('handlers.cognito_backup.boto3.client')
    def test_format_datetime_with_datetime(self, mock_boto3_client):
        """Test datetime formatting with datetime objects."""
        from handlers.cognito_backup import CognitoBackupExporter

        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]

        exporter = CognitoBackupExporter('us-east-1_testpool', 'test-bucket', 'staff')

        test_datetime = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = exporter._format_datetime(test_datetime)  # noqa: SLF001 testing private method

        self.assertEqual(result, '2023-01-01T12:00:00')

    @patch('handlers.cognito_backup.boto3.client')
    def test_format_datetime_with_none(self, mock_boto3_client):
        """Test datetime formatting with None values."""
        from handlers.cognito_backup import CognitoBackupExporter

        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]

        exporter = CognitoBackupExporter('us-east-1_testpool', 'test-bucket', 'staff')
        result = exporter._format_datetime(None)  # noqa: SLF001 testing private method

        self.assertIsNone(result)

    @patch('handlers.cognito_backup.boto3.client')
    def test_export_single_user_missing_username(self, mock_boto3_client):
        """Test export gracefully handles users without usernames."""
        from handlers.cognito_backup import CognitoBackupExporter

        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]

        user_data = {
            'UserStatus': 'CONFIRMED',
            'Attributes': [],
            # Missing Username
        }

        exporter = CognitoBackupExporter('us-east-1_testpool', 'test-bucket', 'staff')
        # Should not raise an exception
        exporter._export_single_user(user_data, '2023-01-01T00:00:00')  # noqa: SLF001 testing private method

        # Should not call S3 put_object for invalid users
        mock_s3.put_object.assert_not_called()


class TestBackupHandler(TstLambdas):
    """Unit tests for the backup_handler function."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

    @patch('handlers.cognito_backup.CognitoBackupExporter')
    def test_backup_handler_success(self, mock_exporter_class):
        """Test successful backup handler execution."""
        from handlers.cognito_backup import backup_handler

        # Mock the exporter
        mock_exporter = MagicMock()
        mock_exporter.export_user_pool.return_value = {
            'users_exported': 5,
            'user_pool_type': 'staff',
            'user_pool_id': 'us-east-1_testpool',
        }
        mock_exporter_class.return_value = mock_exporter

        # Test event and context
        event = {
            'user_pool_id': 'us-east-1_testpool',
            'backup_bucket_name': 'test-backup-bucket',
            'user_pool_type': 'staff',
        }

        result = backup_handler(event, self.mock_context)

        # Verify response
        expected_response = {
            'statusCode': 200,
            'message': 'Cognito backup export completed successfully for staff user pool',
            'results': {'users_exported': 5, 'user_pool_type': 'staff', 'user_pool_id': 'us-east-1_testpool'},
        }
        self.assertEqual(result, expected_response)

        # Verify exporter was called with correct parameters
        mock_exporter_class.assert_called_once_with('us-east-1_testpool', 'test-backup-bucket', 'staff')
        mock_exporter.export_user_pool.assert_called_once()

    @patch('handlers.cognito_backup.CognitoBackupExporter')
    def test_backup_handler_exception(self, mock_exporter_class):
        """Test backup handler with exception."""
        from handlers.cognito_backup import backup_handler

        # Mock the exporter to raise an exception
        mock_exporter = MagicMock()
        mock_exporter.export_user_pool.side_effect = Exception('Export failed')
        mock_exporter_class.return_value = mock_exporter

        event = {
            'user_pool_id': 'us-east-1_testpool',
            'backup_bucket_name': 'test-backup-bucket',
            'user_pool_type': 'staff',
        }

        with self.assertRaises(Exception) as context_mgr:
            backup_handler(event, self.mock_context)

        self.assertEqual(str(context_mgr.exception), 'Export failed')

    def test_backup_handler_missing_event_params(self):
        """Test backup handler with missing event parameters."""
        from handlers.cognito_backup import backup_handler

        # Missing required event parameters
        event = {'user_pool_id': 'us-east-1_testpool'}  # Missing backup_bucket_name and user_pool_type

        with self.assertRaises(ValueError) as context_mgr:
            backup_handler(event, self.mock_context)

        self.assertIn('Missing required parameters', str(context_mgr.exception))

    def test_backup_handler_missing_user_pool_id(self):
        """Test backup handler with missing user_pool_id."""
        from handlers.cognito_backup import backup_handler

        event = {
            'backup_bucket_name': 'test-backup-bucket',
            'user_pool_type': 'staff',
        }

        with self.assertRaises(ValueError) as context_mgr:
            backup_handler(event, self.mock_context)

        self.assertIn('Missing required parameters', str(context_mgr.exception))

    def test_backup_handler_missing_backup_bucket_name(self):
        """Test backup handler with missing backup_bucket_name."""
        from handlers.cognito_backup import backup_handler

        event = {
            'user_pool_id': 'us-east-1_testpool',
            'user_pool_type': 'staff',
        }

        with self.assertRaises(ValueError) as context_mgr:
            backup_handler(event, self.mock_context)

        self.assertIn('Missing required parameters', str(context_mgr.exception))

    def test_backup_handler_missing_user_pool_type(self):
        """Test backup handler with missing user_pool_type."""
        from handlers.cognito_backup import backup_handler

        event = {
            'user_pool_id': 'us-east-1_testpool',
            'backup_bucket_name': 'test-backup-bucket',
        }

        with self.assertRaises(ValueError) as context_mgr:
            backup_handler(event, self.mock_context)

        self.assertIn('Missing required parameters', str(context_mgr.exception))
