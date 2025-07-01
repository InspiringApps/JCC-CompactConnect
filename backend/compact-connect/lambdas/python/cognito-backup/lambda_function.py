"""
Lambda function entry point for Cognito user pool backup.

This module serves as the main entry point for the Lambda function,
delegating to the handlers for the actual backup functionality.
"""

from typing import Any

from handlers.cognito_backup import backup_handler


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler entry point for Cognito user pool backup export.

    :param event: Lambda event containing user pool and bucket information
    :param context: Lambda context
    :return: Response with export results
    """
    return backup_handler(event, context)
