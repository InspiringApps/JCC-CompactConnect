import cc_common.config as cc_config
import common_lambdas.provider_registration as registration_rules
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
from cc_common.config import config, logger, metrics
from cc_common.data_model.provider_record_util import ProviderRecordType
from cc_common.data_model.schema.common import UpdateCategory
from cc_common.data_model.schema.provider import ProviderData, ProviderUpdateData
from cc_common.data_model.schema.provider.api import ProviderRegistrationRequestSchema
from cc_common.exceptions import (
    CCInternalException,
    CCInvalidRequestException,
    CCRateLimitingException,
)
from cc_common.provider_id import provider_id_for_email
from cc_common.utils import api_handler, delayed_function
from marshmallow import ValidationError

COMPACT = 'psypact'
REQUEST_PROCESSED = {'message': 'request processed'}
REGISTRATION_ATTEMPT_METRIC_NAME = 'registration-attempt'


def _use_registration_rules_config() -> None:
    """Point the copied helpers at the PSYPACT config singleton.

    The copied functions read module-level ``config``. That name is bound when
    common-python is imported, and its config class has no provider user pool.
    """
    registration_rules.config = cc_config.config
    registration_rules.logger = cc_config.logger
    registration_rules.metrics = cc_config.metrics


def _load_provider(provider_id: str) -> ProviderData | dict | None:
    """Return the provider record, a raw shell item, or None when nothing is stored."""
    item = config.provider_table.get_item(
        Key={'pk': f'{COMPACT}#PROVIDER#{provider_id}', 'sk': f'{COMPACT}#PROVIDER'},
        ConsistentRead=True,
    ).get('Item')
    if item is None:
        return None
    try:
        return ProviderData.from_database_record(item)
    except ValidationError:
        logger.info('Provider shell is not a full provider record', provider_id=provider_id)
        return item


def _registered_email(provider: ProviderData | dict | None) -> str | None:
    if provider is None:
        return None
    if isinstance(provider, ProviderData):
        return provider.compactConnectRegisteredEmailAddress
    return provider.get('compactConnectRegisteredEmailAddress')


def _create_provider_cognito_user(email: str, provider_id: str) -> None:
    """First-time Cognito create. Cognito sends the temporary-password invite."""
    config.cognito_client.admin_create_user(
        UserPoolId=config.provider_user_pool_id,
        Username=email,
        UserAttributes=[
            {'Name': 'custom:compact', 'Value': COMPACT},
            {'Name': 'custom:providerId', 'Value': provider_id},
            {'Name': 'email', 'Value': email},
            {'Name': 'email_verified', 'Value': 'true'},
        ],
    )


def _delete_cognito_user(email: str) -> None:
    try:
        config.cognito_client.admin_delete_user(UserPoolId=config.provider_user_pool_id, Username=email)
    except ClientError as error:
        logger.error('Failed to roll back Cognito user creation', error=str(error))


def _handle_existing_account(email: str, registered_email: str) -> dict | None:
    """Apply the copied duplicate rules. None means the Cognito user is missing and signup can continue."""
    try:
        cognito_user = config.cognito_client.admin_get_user(UserPoolId=config.provider_user_pool_id, Username=email)
    except ClientError as error:
        if error.response['Error']['Code'] == 'UserNotFoundException':
            logger.error(
                'Provider record shows a registered email but the Cognito user was not found',
                provider_email_registered=registered_email == email,
            )
            return None
        logger.error('Failed to check Cognito user status', error=str(error))
        raise CCInternalException('Failed to check user registration status') from error

    # These helpers are copied private functions. PSYPACT calls them as they are.
    if registration_rules._should_allow_reregistration(cognito_user) and registered_email == email:  # noqa: SLF001
        return registration_rules._resend_invitation_and_complete(email)  # noqa: SLF001

    logger.warning(
        'User attempted to register for an account that already has a registered email.',
        compact=COMPACT,
        user_status=cognito_user['UserStatus'],
        in_force_change_password=cognito_user['UserStatus'] == 'FORCE_CHANGE_PASSWORD',
    )
    return registration_rules._send_registration_attempt_notification_and_complete(  # noqa: SLF001
        registered_email, COMPACT
    )


def _link_registered_email(provider_record: ProviderData, email: str) -> None:
    """Stamp the signup email and write a registration update. Do not rebuild the provider from a license."""
    previous = provider_record.to_dict()
    registration_values = {'compactConnectRegisteredEmailAddress': email}
    now = config.current_standard_datetime
    provider_update_record = ProviderUpdateData.create_new(
        {
            'type': ProviderRecordType.PROVIDER_UPDATE,
            'updateType': UpdateCategory.REGISTRATION,
            'providerId': provider_record.providerId,
            'compact': provider_record.compact,
            'previous': previous,
            'createDate': now,
            'updatedValues': registration_values,
        }
    )
    provider_record.update(registration_values)
    serializer = TypeSerializer()
    config.dynamodb_client.transact_write_items(
        TransactItems=[
            {
                'Put': {
                    'TableName': config.provider_table_name,
                    'Item': serializer.serialize(provider_record.serialize_to_database_record())['M'],
                }
            },
            {
                'Put': {
                    'TableName': config.provider_table_name,
                    'Item': serializer.serialize(provider_update_record.serialize_to_database_record())['M'],
                }
            },
        ]
    )


def _write_provider_shell(provider_id: str, email: str) -> None:
    """Reserve the provider id and registered email. Profile fields are collected later."""
    config.provider_table.put_item(
        Item={
            'pk': f'{COMPACT}#PROVIDER#{provider_id}',
            'sk': f'{COMPACT}#PROVIDER',
            'type': 'provider',
            'compact': COMPACT,
            'providerId': provider_id,
            'compactConnectRegisteredEmailAddress': email,
            'dateOfUpdate': config.current_standard_datetime.isoformat(),
        }
    )


@api_handler
@delayed_function(delay_seconds=2.0)
def register_provider(event: dict, context: LambdaContext):  # noqa: ARG001 unused-argument
    """Create a PSYPACT provider account from an email address.

    :param event: Standard API Gateway event, API schema documented in the CDK ApiStack
    :param LambdaContext context:
    """
    _use_registration_rules_config()
    source_ip = event['requestContext']['identity']['sourceIp']

    try:
        body = ProviderRegistrationRequestSchema().loads(event['body'])
    except ValidationError as error:
        logger.warning('Invalid request body', errors=error.messages)
        raise CCInvalidRequestException(f'Invalid request: {error.messages}') from error

    email = body['email']
    if registration_rules._rate_limit_exceeded(source_ip):  # noqa: SLF001
        logger.warning('Rate limit exceeded for ip address', ip_address=source_ip)
        metrics.add_metric(name='registration-rate-limit-throttles', unit=MetricUnit.Count, value=1)
        metrics.add_metric(name=REGISTRATION_ATTEMPT_METRIC_NAME, unit=MetricUnit.NoUnit, value=0)
        raise CCRateLimitingException('Rate limit exceeded. Please try again later.')

    provider_id = provider_id_for_email(email)
    provider = _load_provider(provider_id)
    registered_email = _registered_email(provider)
    if registered_email is not None:
        existing = _handle_existing_account(email, registered_email)
        if existing is not None:
            return existing

    try:
        _create_provider_cognito_user(email, provider_id)
    except ClientError as error:
        if error.response['Error']['Code'] == 'UsernameExistsException':
            logger.info('User attempted to register with an existing Cognito email', compact=COMPACT)
            return registration_rules._send_registration_attempt_notification_and_complete(  # noqa: SLF001
                email, COMPACT
            )
        logger.error('Failed to create Cognito user', error=str(error))
        metrics.add_metric(name=REGISTRATION_ATTEMPT_METRIC_NAME, unit=MetricUnit.NoUnit, value=0)
        raise CCInternalException('Failed to create user account') from error

    try:
        if isinstance(provider, ProviderData):
            _link_registered_email(provider, email)
        else:
            _write_provider_shell(provider_id, email)
    except Exception as error:
        logger.error('Failed to store registration, rolling back cognito user creation', error=str(error))
        _delete_cognito_user(email)
        metrics.add_metric(name=REGISTRATION_ATTEMPT_METRIC_NAME, unit=MetricUnit.NoUnit, value=0)
        raise CCInternalException('Failed to set registration values') from error

    logger.info('Registered user successfully', compact=COMPACT, provider_id=provider_id)
    metrics.add_metric(name=REGISTRATION_ATTEMPT_METRIC_NAME, unit=MetricUnit.NoUnit, value=1)
    return REQUEST_PROCESSED
