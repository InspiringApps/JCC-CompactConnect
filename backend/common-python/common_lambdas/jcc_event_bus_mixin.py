# Copied method bodies from backend/compact-connect/lambdas/python/common/cc_common/event_bus_client.py

from common_lambdas.config import config
from common_lambdas.data_model.schema.data_event.jcc_home_jurisdiction import HomeJurisdictionChangeEventDetailSchema
from common_lambdas.event_state_client import EventType


class JccEventBusClientMixin:
    def publish_home_jurisdiction_change_event(
        self,
        source: str,
        compact: str,
        provider_id: str,
        previous_home_jurisdiction: str | None,
        new_home_jurisdiction: str,
    ):
        """
        Publish a home jurisdiction change event to the event bus.

        :param source: The source of the event
        :param compact: The compact name
        :param provider_id: The provider ID
        :param previous_home_jurisdiction: Previous home jurisdiction (can be None)
        :param new_home_jurisdiction: New home jurisdiction
        """
        event_detail = {
            'compact': compact,
            'providerId': provider_id,
            'previousHomeJurisdiction': previous_home_jurisdiction,
            'newHomeJurisdiction': new_home_jurisdiction,
            'eventTime': config.current_standard_datetime,
        }

        home_jurisdiction_change_detail_schema = HomeJurisdictionChangeEventDetailSchema()
        deserialized_detail = home_jurisdiction_change_detail_schema.dump(event_detail)

        self._publish_event(
            source=source,
            detail_type=EventType.HOME_JURISDICTION_CHANGE.value,
            detail=deserialized_detail,
        )
