"""
Lambda function to export Cognito user pool data to S3 for backup purposes.

This function exports all user attributes from both staff and provider user pools,
storing each user as a separate JSON file in S3. The function is designed to be
scheduled daily via EventBridge.

Object keys are based on usernames to allow for deterministic file paths
and easy identification during disaster recovery scenarios.
"""
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError

logger = Logger()


class CognitoBackupExporter:
    """Handles the export of Cognito user pool data to S3."""

    def __init__(self):
        self.cognito_client = boto3.client('cognito-idp')
        self.s3_client = boto3.client('s3')
        self.bucket_name = os.environ['BACKUP_BUCKET_NAME']
        self.staff_user_pool_id = os.environ['STAFF_USER_POOL_ID']
        self.provider_user_pool_id = os.environ['PROVIDER_USER_POOL_ID']

    def export_user_pools(self) -> Dict[str, int]:
        """
        Export all users from both staff and provider user pools.
        
        Returns:
            Dict containing export summary with user counts for each pool
        """
        export_timestamp = datetime.utcnow().isoformat()
        
        logger.info("Starting Cognito user pool backup export", {
            "timestamp": export_timestamp,
            "bucket": self.bucket_name
        })
        
        results = {}
        
        # Export staff users
        staff_count = self._export_user_pool(
            user_pool_id=self.staff_user_pool_id,
            user_pool_type="staff",
            export_timestamp=export_timestamp
        )
        results["staff_users_exported"] = staff_count
        
        # Export provider users
        provider_count = self._export_user_pool(
            user_pool_id=self.provider_user_pool_id,
            user_pool_type="provider",
            export_timestamp=export_timestamp
        )
        results["provider_users_exported"] = provider_count
        
        logger.info("Completed Cognito user pool backup export", {
            "results": results,
            "total_users": staff_count + provider_count
        })
        
        return results

    def _export_user_pool(self, user_pool_id: str, user_pool_type: str, export_timestamp: str) -> int:
        """
        Export all users from a specific user pool.
        
        Args:
            user_pool_id: The Cognito user pool ID
            user_pool_type: Type descriptor for the user pool (staff/provider)
            export_timestamp: ISO timestamp for this export batch
            
        Returns:
            Number of users exported
        """
        logger.info(f"Starting export for {user_pool_type} user pool", {
            "user_pool_id": user_pool_id,
            "user_pool_type": user_pool_type
        })
        
        users_exported = 0
        pagination_token = None
        
        while True:
            try:
                # Get a page of users from the user pool
                list_users_kwargs = {
                    'UserPoolId': user_pool_id,
                    'Limit': 60  # Max allowed per API call
                }
                
                if pagination_token:
                    list_users_kwargs['PaginationToken'] = pagination_token
                
                response = self.cognito_client.list_users(**list_users_kwargs)
                users = response.get('Users', [])
                
                logger.info(f"Retrieved {len(users)} users from {user_pool_type} user pool", {
                    "page_size": len(users),
                    "has_next_page": 'PaginationToken' in response
                })
                
                # Export each user to S3
                for user in users:
                    self._export_single_user(user, user_pool_type, export_timestamp)
                    users_exported += 1
                
                # Check if there are more pages
                pagination_token = response.get('PaginationToken')
                if not pagination_token:
                    break
                    
            except ClientError as e:
                logger.error(f"Error listing users from {user_pool_type} user pool", {
                    "error": str(e),
                    "user_pool_id": user_pool_id
                })
                raise
        
        logger.info(f"Completed export for {user_pool_type} user pool", {
            "users_exported": users_exported
        })
        
        return users_exported

    def _export_single_user(self, user: Dict, user_pool_type: str, export_timestamp: str) -> None:
        """
        Export a single user's data to S3.
        
        Args:
            user: User data from Cognito list_users API
            user_pool_type: Type descriptor for the user pool (staff/provider)
            export_timestamp: ISO timestamp for this export batch
        """
        # Extract username - this is our key for the S3 object
        username = user.get('Username')
        if not username:
            logger.warning("User missing username, skipping export", {"user": user})
            return
        
        # Create comprehensive user export data
        export_data = {
            'export_metadata': {
                'export_timestamp': export_timestamp,
                'user_pool_type': user_pool_type,
                'export_version': '1.0'
            },
            'user_data': {
                'username': username,
                'user_status': user.get('UserStatus'),
                'enabled': user.get('Enabled'),
                'user_create_date': user.get('UserCreateDate').isoformat() if user.get('UserCreateDate') is not None else None,
                'user_last_modified_date': user.get('UserLastModifiedDate').isoformat() if user.get('UserLastModifiedDate') is not None else None,
                'mfa_options': user.get('MFAOptions', []),
                'attributes': self._extract_user_attributes(user.get('Attributes', []))
            }
        }
        
        # Create S3 object key based on username
        # Format: cognito-exports/{user_pool_type}/{username}.json
        object_key = f"cognito-exports/{user_pool_type}/{username}.json"
        
        try:
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=json.dumps(export_data, indent=2, default=str),
                ContentType='application/json',
                # Add metadata for operational tracking
                Metadata={
                    'export-timestamp': export_timestamp,
                    'user-pool-type': user_pool_type,
                    'username': username
                }
            )
            
            logger.debug(f"Exported user {username} to S3", {
                "username": username,
                "object_key": object_key,
                "user_pool_type": user_pool_type
            })
            
        except ClientError as e:
            logger.error(f"Failed to export user {username} to S3", {
                "username": username,
                "object_key": object_key,
                "error": str(e)
            })
            raise

    def _extract_user_attributes(self, attributes: List[Dict]) -> Dict[str, str]:
        """
        Convert Cognito user attributes list to a dictionary.
        
        Args:
            attributes: List of attribute dicts from Cognito API
            
        Returns:
            Dictionary mapping attribute names to values
        """
        return {attr['Name']: attr['Value'] for attr in attributes}


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: Dict, context: LambdaContext) -> Dict:
    """
    Lambda handler for Cognito user pool backup export.
    
    This function is designed to be triggered by EventBridge on a daily schedule.
    It exports all users from both staff and provider user pools to S3.
    
    Args:
        event: EventBridge event (scheduled trigger)
        context: Lambda context
        
    Returns:
        Dictionary containing export results summary
    """
    try:
        exporter = CognitoBackupExporter()
        results = exporter.export_user_pools()
        
        logger.info("Cognito backup export completed successfully", {
            "results": results
        })
        
        return {
            'statusCode': 200,
            'message': 'Cognito backup export completed successfully',
            'results': results
        }
        
    except Exception as e:
        logger.error("Cognito backup export failed", {
            "error": str(e)
        })
        raise