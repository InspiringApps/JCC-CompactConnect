# ruff: noqa: N801, N802, N811, N815, ARG002  invalid-name unused-argument
from datetime import date
from uuid import UUID

from marshmallow import pre_dump
from marshmallow.fields import UUID as MarshmallowUUID
from marshmallow.fields import Boolean, Date, String
from marshmallow.validate import OneOf

from common_lambdas.data_model.schema.base_record import BaseRecordSchema
from common_lambdas.data_model.schema.common import CCDataClass
from common_lambdas.data_model.schema.fields import Compact

AUTHORIZATION_RECORD_TYPE = 'authorization'
AUTHORIZATION_TYPES = ('APIT', 'TAP')


@BaseRecordSchema.register_schema(AUTHORIZATION_RECORD_TYPE)
class AuthorizationRecordSchema(BaseRecordSchema):
    """
    One current APIT or TAP authorization for a practitioner.

    The record is not tied to a license. Renewal replaces this item.
    isActive is the stored approval flag. Whether the authorization can
    generate privileges is calculated at read time.

    Serialization direction:
    DB -> load() -> Python
    """

    _record_type = AUTHORIZATION_RECORD_TYPE

    providerId = MarshmallowUUID(required=True, allow_none=False)
    compact = Compact(required=True, allow_none=False)
    authorizationType = String(required=True, allow_none=False, validate=OneOf(AUTHORIZATION_TYPES))
    dateOfExpiration = Date(required=True, allow_none=False)
    isActive = Boolean(required=True, allow_none=False)

    @pre_dump
    def generate_pk_sk(self, in_data, **kwargs):  # noqa: ARG001 unused-argument
        provider_id = in_data['providerId']
        in_data['pk'] = f'{in_data["compact"]}#PROVIDER#{provider_id}'
        in_data['sk'] = f'{in_data["compact"]}#PROVIDER#authorization/{in_data["authorizationType"]}#'
        return in_data


class AuthorizationData(CCDataClass):
    """Practitioner authorization loaded from the provider table."""

    _record_schema = AuthorizationRecordSchema()
    _requires_data_at_construction = True

    @property
    def providerId(self) -> UUID:
        return self._data['providerId']

    @property
    def compact(self) -> str:
        return self._data['compact']

    @property
    def authorizationType(self) -> str:
        return self._data['authorizationType']

    @property
    def dateOfExpiration(self) -> date:
        return self._data['dateOfExpiration']

    @property
    def isActive(self) -> bool:
        return self._data['isActive']
