import json

from aws_lambda_powertools.utilities.typing import LambdaContext
from common_lambdas.config import config, logger
from common_lambdas.data_model.schema.common import CompactEligibilityStatus
from common_lambdas.data_model.schema.fields import OTHER_JURISDICTION, UNKNOWN_JURISDICTION
from common_lambdas.exceptions import CCInvalidRequestException
from common_lambdas.psypact_records import license_is_unexpired
from common_lambdas.utils import api_handler, get_provider_user_attributes_from_authorizer_claims

from .provider_users import _put_provider_home_jurisdiction


def _selected_jurisdiction_has_valid_license(*, compact: str, provider_id: str, selected_jurisdiction: str) -> bool:
    if selected_jurisdiction in {OTHER_JURISDICTION, UNKNOWN_JURISDICTION}:
        return False
    provider_records = config.data_client.get_provider_user_records(compact=compact, provider_id=provider_id)
    return any(
        license_record.jurisdiction.lower() == selected_jurisdiction
        and license_record.compactEligibility == CompactEligibilityStatus.ELIGIBLE
        and license_is_unexpired(license_record)
        for license_record in provider_records.get_license_records()
    )


@api_handler
def put_psypact_provider_home_jurisdiction(event: dict, context: LambdaContext):
    """Reject home-jurisdiction changes unless a valid license exists in the target state."""
    event_body = json.loads(event['body'])
    selected_jurisdiction = event_body['jurisdiction'].lower()
    compact, provider_id = get_provider_user_attributes_from_authorizer_claims(event)

    if not _selected_jurisdiction_has_valid_license(
        compact=compact,
        provider_id=provider_id,
        selected_jurisdiction=selected_jurisdiction,
    ):
        logger.info(
            'Rejecting home jurisdiction change without a valid license in the selected state',
            compact=compact,
            provider_id=provider_id,
            selected_jurisdiction=selected_jurisdiction,
        )
        raise CCInvalidRequestException(
            'A valid compact-eligible license is required in the selected home jurisdiction.'
        )

    return _put_provider_home_jurisdiction.__wrapped__(event, context)
