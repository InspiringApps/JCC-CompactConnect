# Copied from backend/compact-connect/lambdas/python/common/cc_common/data_model/schema/fields.py

from marshmallow.fields import String
from marshmallow.validate import OneOf

from common_lambdas.config import config
from common_lambdas.data_model.schema.common import MilitaryStatus
from common_lambdas.data_model.schema.fields import OTHER_JURISDICTION, UNKNOWN_JURISDICTION


class CurrentHomeJurisdictionField(String):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, validate=OneOf(config.jurisdictions + [OTHER_JURISDICTION, UNKNOWN_JURISDICTION]), **kwargs
        )


class MilitaryStatusField(String):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, validate=OneOf([entry.value for entry in MilitaryStatus]), **kwargs)
