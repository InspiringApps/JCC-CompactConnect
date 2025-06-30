"""
Unit tests for the Cognito backup Lambda function.

This module tests the CognitoBackupExporter class and lambda_handler function
to ensure proper export of user pool data to S3.
"""
import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch
from unittest import TestCase

from botocore.exceptions import ClientError


class TestCognitoBackupExporter(TestCase):
    """Test cases for the CognitoBackupExporter class."""

    def setUp(self):
        """Set up test fixtures."""
        # Set required environment variables
        os.environ['BACKUP_BUCKET_NAME'] = 'test-cognito-backup-bucket'
        os.environ['STAFF_USER_POOL_ID'] = 'us-east-1_staffpool'
        os.environ['PROVIDER_USER_POOL_ID'] = 'us-east-1_providerpo'
        
        # Import after setting environment variables
        from lambda_function import CognitoBackupExporter
        self.CognitoBackupExporter = CognitoBackupExporter

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up environment variables
        for key in ['BACKUP_BUCKET_NAME', 'STAFF_USER_POOL_ID', 'PROVIDER_USER_POOL_ID']:
            if key in os.environ:
                del os.environ[key]

    @patch('lambda_function.boto3.client')
    def test_init(self, mock_boto3_client):
        """Test CognitoBackupExporter initialization."""
        exporter = self.CognitoBackupExporter()
        
        # Verify boto3 clients are created
        self.assertEqual(mock_boto3_client.call_count, 2)
        mock_boto3_client.assert_any_call('cognito-idp')
        mock_boto3_client.assert_any_call('s3')
        
        # Verify environment variables are set correctly
        self.assertEqual(exporter.bucket_name, 'test-cognito-backup-bucket')
        self.assertEqual(exporter.staff_user_pool_id, 'us-east-1_staffpool')
        self.assertEqual(exporter.provider_user_pool_id, 'us-east-1_providerpo')

    @patch('lambda_function.boto3.client')
    def test_export_user_pools_success(self, mock_boto3_client):
        """Test successful export of both user pools."""
        # Mock Cognito client
        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]
        
        # Mock Cognito list_users responses
        mock_cognito.list_users.side_effect = [
            {
                'Users': [
                    {
                        'Username': 'staff-user1',
                        'UserStatus': 'CONFIRMED',
                        'Enabled': True,
                        'UserCreateDate': datetime(2023, 1, 1, 12, 0, 0),
                        'UserLastModifiedDate': datetime(2023, 1, 2, 12, 0, 0),
                        'MFAOptions': [],
                        'Attributes': [
                            {'Name': 'email', 'Value': 'staff1@example.com'},
                            {'Name': 'email_verified', 'Value': 'true'},
                        ]
                    }
                ]
                # No PaginationToken - single page
            },
            {
                'Users': [
                    {
                        'Username': 'provider-user1',
                        'UserStatus': 'CONFIRMED',
                        'Enabled': True,
                        'UserCreateDate': datetime(2023, 1, 1, 12, 0, 0),
                        'UserLastModifiedDate': datetime(2023, 1, 2, 12, 0, 0),
                        'MFAOptions': [],
                        'Attributes': [
                            {'Name': 'email', 'Value': 'provider1@example.com'},
                            {'Name': 'custom:providerId', 'Value': 'prov123'},
                            {'Name': 'custom:compact', 'Value': 'aslp'},
                        ]
                    }
                ]
                # No PaginationToken - single page
            }
        ]
        
        exporter = self.CognitoBackupExporter()
        results = exporter.export_user_pools()
        
        # Verify results
        self.assertEqual(results['staff_users_exported'], 1)
        self.assertEqual(results['provider_users_exported'], 1)
        
        # Verify Cognito calls
        self.assertEqual(mock_cognito.list_users.call_count, 2)
        mock_cognito.list_users.assert_any_call(UserPoolId='us-east-1_staffpool', Limit=60)
        mock_cognito.list_users.assert_any_call(UserPoolId='us-east-1_providerpo', Limit=60)
        
        # Verify S3 put_object calls
        self.assertEqual(mock_s3.put_object.call_count, 2)

    @patch('lambda_function.boto3.client')
    def test_export_user_pool_pagination(self, mock_boto3_client):
        """Test export with pagination through multiple pages."""
        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]
        
        # Mock paginated response
        mock_cognito.list_users.side_effect = [
            {
                'Users': [{'Username': 'user1', 'Attributes': []}],
                'PaginationToken': 'token123'
            },
            {
                'Users': [{'Username': 'user2', 'Attributes': []}]
                # No PaginationToken - last page
            }
        ]
        
        exporter = self.CognitoBackupExporter()
        result = exporter._export_user_pool('test-pool-id', 'test', '2023-01-01T00:00:00')
        
        # Verify pagination was handled
        self.assertEqual(result, 2)
        self.assertEqual(mock_cognito.list_users.call_count, 2)
        
        # Verify pagination token was used
        calls = mock_cognito.list_users.call_args_list
        self.assertEqual(calls[0][1]['UserPoolId'], 'test-pool-id')
        self.assertNotIn('PaginationToken', calls[0][1])  # First call has no token
        self.assertEqual(calls[1][1]['PaginationToken'], 'token123')  # Second call has token

    @patch('lambda_function.boto3.client')
    def test_export_single_user_complete_data(self, mock_boto3_client):
        """Test export of a single user with complete data."""
        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]
        
        user_data = {
            'Username': 'test-user',
            'UserStatus': 'CONFIRMED',
            'Enabled': True,
            'UserCreateDate': datetime(2023, 1, 1, 12, 0, 0),
            'UserLastModifiedDate': datetime(2023, 1, 2, 12, 0, 0),
            'MFAOptions': [{'DeliveryMedium': 'SMS', 'AttributeName': 'phone_number'}],
            'Attributes': [
                {'Name': 'email', 'Value': 'test@example.com'},
                {'Name': 'given_name', 'Value': 'Test'},
                {'Name': 'family_name', 'Value': 'User'},
            ]
        }
        
        exporter = self.CognitoBackupExporter()
        exporter._export_single_user(user_data, 'staff', '2023-01-01T00:00:00')
        
        # Verify S3 put_object was called with correct data
        mock_s3.put_object.assert_called_once()
        call_args = mock_s3.put_object.call_args
        
        self.assertEqual(call_args[1]['Bucket'], 'test-cognito-backup-bucket')
        self.assertEqual(call_args[1]['Key'], 'cognito-exports/staff/test-user.json')
        self.assertEqual(call_args[1]['ContentType'], 'application/json')
        
        # Verify metadata
        expected_metadata = {
            'export-timestamp': '2023-01-01T00:00:00',
            'user-pool-type': 'staff',
            'username': 'test-user'
        }
        self.assertEqual(call_args[1]['Metadata'], expected_metadata)
        
        # Verify JSON content structure
        json_content = json.loads(call_args[1]['Body'])
        self.assertIn('export_metadata', json_content)
        self.assertIn('user_data', json_content)
        
        # Verify export metadata
        export_meta = json_content['export_metadata']
        self.assertEqual(export_meta['export_timestamp'], '2023-01-01T00:00:00')
        self.assertEqual(export_meta['user_pool_type'], 'staff')
        self.assertEqual(export_meta['export_version'], '1.0')
        
        # Verify user data
        user_export = json_content['user_data']
        self.assertEqual(user_export['username'], 'test-user')
        self.assertEqual(user_export['user_status'], 'CONFIRMED')
        self.assertTrue(user_export['enabled'])
        self.assertEqual(user_export['user_create_date'], '2023-01-01T12:00:00')
        self.assertEqual(user_export['user_last_modified_date'], '2023-01-02T12:00:00')
        
        # Verify attributes conversion
        expected_attributes = {
            'email': 'test@example.com',
            'given_name': 'Test',
            'family_name': 'User'
        }
        self.assertEqual(user_export['attributes'], expected_attributes)

    @patch('lambda_function.boto3.client')
    def test_export_single_user_missing_username(self, mock_boto3_client):
        """Test export gracefully handles users without usernames."""
        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]
        
        user_data = {
            'UserStatus': 'CONFIRMED',
            'Attributes': []
            # Missing Username
        }
        
        exporter = self.CognitoBackupExporter()
        # Should not raise an exception
        exporter._export_single_user(user_data, 'staff', '2023-01-01T00:00:00')
        
        # Should not call S3 put_object for invalid users
        mock_s3.put_object.assert_not_called()

    @patch('lambda_function.boto3.client')
    def test_export_single_user_none_dates(self, mock_boto3_client):
        """Test export handles None dates correctly."""
        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]
        
        user_data = {
            'Username': 'test-user',
            'UserStatus': 'CONFIRMED',
            'Enabled': True,
            'UserCreateDate': None,
            'UserLastModifiedDate': None,
            'Attributes': []
        }
        
        exporter = self.CognitoBackupExporter()
        exporter._export_single_user(user_data, 'staff', '2023-01-01T00:00:00')
        
        # Verify S3 call was made
        mock_s3.put_object.assert_called_once()
        
        # Verify dates are None in JSON content
        call_args = mock_s3.put_object.call_args
        json_content = json.loads(call_args[1]['Body'])
        user_data_export = json_content['user_data']
        
        self.assertIsNone(user_data_export['user_create_date'])
        self.assertIsNone(user_data_export['user_last_modified_date'])

    @patch('lambda_function.boto3.client')
    def test_extract_user_attributes(self, mock_boto3_client):
        """Test user attributes extraction."""
        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]
        
        attributes = [
            {'Name': 'email', 'Value': 'test@example.com'},
            {'Name': 'given_name', 'Value': 'Test'},
            {'Name': 'family_name', 'Value': 'User'},
            {'Name': 'custom:providerId', 'Value': 'prov123'},
        ]
        
        exporter = self.CognitoBackupExporter()
        result = exporter._extract_user_attributes(attributes)
        
        expected = {
            'email': 'test@example.com',
            'given_name': 'Test',
            'family_name': 'User',
            'custom:providerId': 'prov123'
        }
        self.assertEqual(result, expected)

    @patch('lambda_function.boto3.client')
    def test_cognito_client_error(self, mock_boto3_client):
        """Test handling of Cognito client errors."""
        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]
        
        # Mock Cognito error
        mock_cognito.list_users.side_effect = ClientError(
            {'Error': {'Code': 'InvalidParameterException', 'Message': 'Invalid user pool'}},
            'ListUsers'
        )
        
        exporter = self.CognitoBackupExporter()
        
        with self.assertRaises(ClientError):
            exporter._export_user_pool('invalid-pool-id', 'staff', '2023-01-01T00:00:00')

    @patch('lambda_function.boto3.client')
    def test_s3_client_error(self, mock_boto3_client):
        """Test handling of S3 client errors."""
        mock_cognito = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3_client.side_effect = [mock_cognito, mock_s3]
        
        # Mock S3 error
        mock_s3.put_object.side_effect = ClientError(
            {'Error': {'Code': 'NoSuchBucket', 'Message': 'Bucket does not exist'}},
            'PutObject'
        )
        
        user_data = {
            'Username': 'test-user',
            'UserStatus': 'CONFIRMED',
            'Attributes': []
        }
        
        exporter = self.CognitoBackupExporter()
        
        with self.assertRaises(ClientError):
            exporter._export_single_user(user_data, 'staff', '2023-01-01T00:00:00')


class TestLambdaHandler(TestCase):
    """Test cases for the lambda_handler function."""

    def setUp(self):
        """Set up test fixtures."""
        # Set required environment variables
        os.environ['BACKUP_BUCKET_NAME'] = 'test-cognito-backup-bucket'
        os.environ['STAFF_USER_POOL_ID'] = 'us-east-1_staffpool'
        os.environ['PROVIDER_USER_POOL_ID'] = 'us-east-1_providerpo'

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up environment variables
        for key in ['BACKUP_BUCKET_NAME', 'STAFF_USER_POOL_ID', 'PROVIDER_USER_POOL_ID']:
            if key in os.environ:
                del os.environ[key]

    @patch('lambda_function.CognitoBackupExporter')
    def test_lambda_handler_success(self, mock_exporter_class):
        """Test successful lambda handler execution."""
        # Mock the exporter
        mock_exporter = MagicMock()
        mock_exporter.export_user_pools.return_value = {
            'staff_users_exported': 5,
            'provider_users_exported': 10
        }
        mock_exporter_class.return_value = mock_exporter
        
        from lambda_function import lambda_handler
        
        # Test event and context
        event = {'source': 'aws.events'}
        context = MagicMock()
        context.aws_request_id = 'test-request-id'
        
        result = lambda_handler(event, context)
        
        # Verify response
        expected_response = {
            'statusCode': 200,
            'message': 'Cognito backup export completed successfully',
            'results': {
                'staff_users_exported': 5,
                'provider_users_exported': 10
            }
        }
        self.assertEqual(result, expected_response)
        
        # Verify exporter was called
        mock_exporter_class.assert_called_once()
        mock_exporter.export_user_pools.assert_called_once()

    @patch('lambda_function.CognitoBackupExporter')
    def test_lambda_handler_exception(self, mock_exporter_class):
        """Test lambda handler with exception."""
        # Mock the exporter to raise an exception
        mock_exporter = MagicMock()
        mock_exporter.export_user_pools.side_effect = Exception('Export failed')
        mock_exporter_class.return_value = mock_exporter
        
        from lambda_function import lambda_handler
        
        event = {'source': 'aws.events'}
        context = MagicMock()
        
        with self.assertRaises(Exception) as context_mgr:
            lambda_handler(event, context)
        
        self.assertEqual(str(context_mgr.exception), 'Export failed')

    def test_lambda_handler_missing_env_vars(self):
        """Test lambda handler with missing environment variables."""
        # Remove required environment variable
        del os.environ['BACKUP_BUCKET_NAME']
        
        from lambda_function import lambda_handler
        
        event = {'source': 'aws.events'}
        context = MagicMock()
        
        with self.assertRaises(KeyError):
            lambda_handler(event, context)