"""
Cognito user pool backup handlers.

This module contains the CognitoBackupExporter class and related functionality
for exporting Cognito user pool data to S3 for backup purposes.
"""

import json
import logging
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


class CognitoBackupExporter:
    """
    Exports Cognito user pool data to S3 for backup purposes.

    This class handles the export of all users from a single Cognito user pool,
    storing each user as a separate JSON file with comprehensive user data
    including attributes, status, and metadata.
    """

    def __init__(self, user_pool_id: str, backup_bucket_name: str, user_pool_type: str):
        """
        Initialize the Cognito backup exporter.

        :param user_pool_id: The ID of the Cognito user pool to export
        :param backup_bucket_name: The name of the S3 bucket to store exports
        :param user_pool_type: The type of user pool for organization (e.g., 'staff', 'provider')
        """
        self.user_pool_id = user_pool_id
        self.backup_bucket_name = backup_bucket_name
        self.user_pool_type = user_pool_type

        # Initialize AWS clients
        self.cognito_client = boto3.client('cognito-idp')
        self.s3_client = boto3.client('s3')

        logger.info('Initialized Cognito backup exporter for %s user pool %s', user_pool_type, user_pool_id)

    def export_user_pool(self) -> dict[str, Any]:
        """
        Export all users from the specified user pool to S3.

        :return: Dictionary containing export results and metadata
        """
        logger.info('Starting export of %s user pool %s', self.user_pool_type, self.user_pool_id)

        export_timestamp = datetime.now(tz=datetime.timezone.utc).isoformat()
        users_exported = 0

        try:
            # Export all users from the user pool
            users_exported = self._export_user_pool(export_timestamp)

            logger.info('Successfully exported %d users from %s user pool', users_exported, self.user_pool_type)

            return {
                'user_pool_id': self.user_pool_id,
                'user_pool_type': self.user_pool_type,
                'users_exported': users_exported,
                'export_timestamp': export_timestamp,
                'backup_bucket': self.backup_bucket_name,
                'status': 'success',
            }

        except Exception as e:
            logger.error('Failed to export %s user pool: %s', self.user_pool_type, str(e))
            raise

    def _export_user_pool(self, export_timestamp: str) -> int:
        """
        Export all users from the user pool with pagination support.

        :param export_timestamp: ISO timestamp for the export
        :return: Number of users exported
        """
        users_exported = 0
        pagination_token = None

        while True:
            # List users with pagination
            list_params = {
                'UserPoolId': self.user_pool_id,
                'Limit': 60,  # Maximum allowed by Cognito
            }

            if pagination_token:
                list_params['PaginationToken'] = pagination_token

            try:
                response = self.cognito_client.list_users(**list_params)
                users = response.get('Users', [])

                # Export each user
                for user in users:
                    try:
                        self._export_single_user(user, export_timestamp)
                        users_exported += 1
                    except (ClientError, ValueError) as e:
                        logger.error('Failed to export user %s: %s', user.get("Username", "unknown"), str(e))
                        # Continue with other users even if one fails

                # Check for more pages
                pagination_token = response.get('PaginationToken')
                if not pagination_token:
                    break

            except ClientError as e:
                logger.error('Cognito API error: %s', str(e))
                raise

        return users_exported

    def _export_single_user(self, user_data: dict[str, Any], export_timestamp: str) -> None:
        """
        Export a single user to S3 as a JSON file.

        :param user_data: User data from Cognito
        :param export_timestamp: ISO timestamp for the export
        """
        username = user_data.get('Username')
        if not username:
            logger.warning('Skipping user without username')
            return

        # Create object key based on username
        object_key = f'cognito-exports/{self.user_pool_type}/{username}.json'

        # Prepare export data
        export_data = {
            'export_metadata': {
                'export_timestamp': export_timestamp,
                'user_pool_id': self.user_pool_id,
                'user_pool_type': self.user_pool_type,
                'export_version': '1.0',
            },
            'user_data': {
                'username': username,
                'user_status': user_data.get('UserStatus'),
                'enabled': user_data.get('Enabled', False),
                'user_create_date': self._format_datetime(user_data.get('UserCreateDate')),
                'user_last_modified_date': self._format_datetime(user_data.get('UserLastModifiedDate')),
                'mfa_options': user_data.get('MFAOptions', []),
                'attributes': self._extract_user_attributes(user_data.get('Attributes', [])),
            },
        }

        # Upload to S3
        try:
            self.s3_client.put_object(
                Bucket=self.backup_bucket_name,
                Key=object_key,
                Body=json.dumps(export_data, indent=2, default=str),
                ContentType='application/json',
                Metadata={
                    'export-timestamp': export_timestamp,
                    'user-pool-type': self.user_pool_type,
                    'username': username,
                },
            )

            logger.debug('Exported user %s to %s', username, object_key)

        except ClientError as e:
            logger.error('Failed to upload user %s to S3: %s', username, str(e))
            raise

    def _extract_user_attributes(self, attributes: list[dict[str, str]]) -> dict[str, str]:
        """
        Extract user attributes from Cognito format to a simple key-value dictionary.

        :param attributes: List of Cognito user attributes
        :return: Dictionary of attribute names to values
        """
        extracted = {}
        for attr in attributes:
            name = attr.get('Name')
            value = attr.get('Value')
            if name and value is not None:
                extracted[name] = value
        return extracted

    def _format_datetime(self, dt) -> str:
        """
        Format datetime object to ISO string, handling None values.

        :param dt: Datetime object or None
        :return: ISO formatted string or None
        """
        if dt is None:
            return None
        if hasattr(dt, 'isoformat'):
            return dt.isoformat()
        return str(dt)


def backup_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001 unused-argument
    """
    Handler for Cognito user pool backup export.

    Expected event format:
    {
        "user_pool_id": "us-east-1_xxxxxxxxx",
        "backup_bucket_name": "my-cognito-backup-bucket",
        "user_pool_type": "staff"
    }

    :param event: Lambda event containing user pool and bucket information
    :param context: Lambda context
    :return: Response with export results
    """
    logger.info('Received event: %s', json.dumps(event))

    try:
        # Extract parameters from event
        user_pool_id = event.get('user_pool_id')
        backup_bucket_name = event.get('backup_bucket_name')
        user_pool_type = event.get('user_pool_type')

        if not all([user_pool_id, backup_bucket_name, user_pool_type]):
            raise ValueError('Missing required parameters: user_pool_id, backup_bucket_name, user_pool_type')

        # Create exporter and run export
        exporter = CognitoBackupExporter(user_pool_id, backup_bucket_name, user_pool_type)
        results = exporter.export_user_pool()

        logger.info('Export completed successfully: %s', json.dumps(results))

        return {
            'statusCode': 200,
            'message': f'Cognito backup export completed successfully for {user_pool_type} user pool',
            'results': results,
        }

    except Exception as e:
        logger.error('Export failed: %s', str(e))
        raise
