# pylint: disable=unused-argument,unexpected-keyword-arg,missing-kwoa
# Pylint really butchers these function signatures because they are modified via decorator
# to cut down on noise level, we're disabling those rules for the whole module

from aws_lambda_powertools.utilities.typing import LambdaContext

from exceptions import CCInvalidRequestException
from handlers.utils import api_handler, authorize_compact
from config import logger
from . import get_provider_information

@api_handler
def get_provider(event: dict, context: LambdaContext):  # pylint: disable=unused-argument
    """
    Return one provider's data
    :param event: Standard API Gateway event, API schema documented in the CDK ApiStack
    :param LambdaContext context:
    """
    try:
        # the two values for compact and providerId are stored as custom attributes in the user's cognito claims
        # so we can access them directly from the event object
        compact = event['requestContext']['authorizer']['claims']['custom:compact']
        provider_id = event['requestContext']['authorizer']['claims']['custom:compact']
    except (KeyError, TypeError) as e:
        # This shouldn't happen unless a provider user was created without these custom attributes,
        # but we'll handle it, anyway
        logger.error(f'Missing custom provider attribute: {e}')
        raise CCInvalidRequestException('Missing required user profile attribute') from e

    return get_provider_information(compact=compact, provider_id=provider_id)
