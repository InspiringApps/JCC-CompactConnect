from uuid import UUID

from common_lambdas.config import logger
from common_lambdas.data_model.data_client import DataClient
from common_lambdas.data_model.jcc_data_client_mixin import JccDataClientMixin
from common_lambdas.data_model.update_tier_enum import UpdateTierEnum
from common_lambdas.psypact_records import PsypactProviderUserRecords
from common_lambdas.utils import logger_inject_kwargs


class PsypactDataClient(JccDataClientMixin, DataClient):
    """Cosmetology DataClient plus selected JCC DataClient methods, returning PSYPACT records."""

    @logger_inject_kwargs(logger, 'compact', 'provider_id')
    def get_provider_user_records(
        self,
        compact: str,
        provider_id: UUID,
        consistent_read: bool = False,
        include_update_tier: UpdateTierEnum | None = None,
    ) -> PsypactProviderUserRecords:
        records = super().get_provider_user_records(
            compact=compact,
            provider_id=provider_id,
            consistent_read=consistent_read,
            include_update_tier=include_update_tier,
        )
        return PsypactProviderUserRecords(records.provider_records)
