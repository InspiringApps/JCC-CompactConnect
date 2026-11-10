# Copied method bodies from backend/compact-connect/lambdas/python/provider-data-v1/handlers/registration.py

from datetime import timedelta

from aws_lambda_powertools.metrics import MetricUnit
from botocore.exceptions import ClientError

from common_lambdas.config import config, logger, metrics
from common_lambdas.exceptions import CCAwsServiceException

REGISTRATION_ATTEMPT_METRIC_NAME = 'registration-attempt'


def _rate_limit_exceeded(ip_address: str) -> bool:
    """Check if the IP address has exceeded the rate limit.

    :return: True if rate limit is exceeded, False otherwise
    """
    now = config.current_standard_datetime
    window_start = now - timedelta(minutes=15)
    window_start_str = window_start.isoformat()

    try:
        # Query for count of requests in the last 15 minutes
        response = config.rate_limiting_table.query(
            KeyConditionExpression='pk = :pk AND sk BETWEEN :start_sk AND :end_sk',
            ExpressionAttributeValues={
                ':pk': f'IP#{ip_address}',
                ':start_sk': f'REGISTRATION#{window_start_str}',
                ':end_sk': f'REGISTRATION#{now.isoformat()}',
            },
            Select='COUNT',
            ConsistentRead=True,
        )

        # If there are 3 or more requests in the window, rate limit is exceeded
        if response['Count'] >= 3:
            logger.warning('Rate limit exceeded', ip_address=ip_address)
            return True

        # Add the current request
        config.rate_limiting_table.put_item(
            Item={
                'pk': f'IP#{ip_address}',
                'sk': f'REGISTRATION#{now.isoformat()}',
                'ttl': int(now.timestamp()) + 900,  # 15 minutes in seconds
            }
        )
        return False
    except ClientError as e:
        logger.error('Failed to check rate limit', error=str(e))
        raise CCAwsServiceException('Failed to check rate limit') from e


def _should_allow_reregistration(cognito_user: dict) -> bool:
    """Check if a user should be allowed to re-register based on their Cognito status.

    :param cognito_user: Cognito user response from admin_get_user
    :return: True if re-registration should be allowed
    """
    user_last_modified_date = cognito_user['UserLastModifiedDate']
    user_status = cognito_user['UserStatus']

    updated_over_one_day_ago = (config.current_standard_datetime - user_last_modified_date) > timedelta(days=1)
    in_force_change_password = user_status == 'FORCE_CHANGE_PASSWORD'

    return updated_over_one_day_ago and in_force_change_password


def _resend_invitation_and_complete(email: str) -> dict:
    """Resend invitation to existing user with same email and return response.

    :param email: Email address to resend invitation to
    :return: Response dictionary
    """
    logger.info('User re-registering with same email address. Resending invite.')
    config.cognito_client.admin_create_user(
        UserPoolId=config.provider_user_pool_id, Username=email, MessageAction='RESEND'
    )
    metrics.add_metric(name=REGISTRATION_ATTEMPT_METRIC_NAME, unit=MetricUnit.NoUnit, value=1)
    return {'message': 'request processed'}


def _cleanup_old_registration(old_email: str, cognito_user: dict, provider_id: str) -> None:
    """Delete old Cognito user to allow new registration.

    :param old_email: Email of the old registration to clean up
    :param cognito_user: Cognito user data for logging
    :param provider_id: The provider ID associated with the old registration, for non-PII log traceability
    """
    try:
        logger.info(
            'User never completed registration flow for previous email and has provided new email for registration, '
            'deleting old Cognito user associated with previous email.',
            provider_id=provider_id,
            user_create_date=cognito_user['UserCreateDate'].isoformat(),
            user_last_modified_date=cognito_user['UserLastModifiedDate'].isoformat(),
            user_status=cognito_user['UserStatus'],
        )
        config.cognito_client.admin_delete_user(UserPoolId=config.provider_user_pool_id, Username=old_email)
    except ClientError as delete_e:
        logger.error(
            'Failed to delete old Cognito user during re-registration', error=str(delete_e), provider_id=provider_id
        )
        # Continue with registration anyway


def _send_registration_attempt_notification_and_complete(registered_email: str, compact: str) -> dict:
    """Send registration attempt notification email and return completed response.

    :param registered_email: Email address registered in system
    :param compact: Compact name
    :return: Response dictionary
    """
    config.email_service_client.send_provider_multiple_registration_attempt_email(
        compact=compact, provider_email=registered_email
    )
    metrics.add_metric(name=REGISTRATION_ATTEMPT_METRIC_NAME, unit=MetricUnit.NoUnit, value=0)
    return {'message': 'request processed'}
