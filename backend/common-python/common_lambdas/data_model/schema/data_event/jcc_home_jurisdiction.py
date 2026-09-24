# Copied from backend/compact-connect/lambdas/python/common/cc_common/data_model/schema/data_event/api.py

from marshmallow.fields import UUID, AwareDateTime, String

from common_lambdas.data_model.schema.base_record import ForgivingSchema
from common_lambdas.data_model.schema.fields import Compact


class HomeJurisdictionChangeEventDetailSchema(ForgivingSchema):
    """Schema for home jurisdiction change events"""

    compact = Compact(required=True, allow_none=False)
    providerId = UUID(required=True, allow_none=False)
    previousHomeJurisdiction = String(required=True, allow_none=True)
    newHomeJurisdiction = String(required=True, allow_none=False)
    eventTime = AwareDateTime(required=True, allow_none=False)
