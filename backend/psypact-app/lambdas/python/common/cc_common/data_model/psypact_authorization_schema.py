# ruff: noqa: N815  invalid-name
"""PSYPACT authorization record, including the stored renewal standing.

Privilege generation, license status, and isActive do not read renewalStatus.
The name is the stored RenewalProcessTypeState.Status, not a value derived by
GetTrueStatus.
"""

from common_lambdas.data_model.schema.base_record import BaseRecordSchema
from common_lambdas.schema.authorization import AUTHORIZATION_RECORD_TYPE, AuthorizationRecordSchema
from marshmallow.fields import String
from marshmallow.validate import OneOf

RENEWAL_STATUS_NAMES = (
    'Active',
    'Inactive/Retired',
    'Expired 1',
    'Expired 2',
    'Permanently Expired',
    'Revoked',
    'Voluntary Resign',
    'Active*',
    'Suspended',
    'Abeyance',
    'Deceased',
    'Closed',
)


@BaseRecordSchema.register_schema(AUTHORIZATION_RECORD_TYPE)
class PsypactAuthorizationRecordSchema(AuthorizationRecordSchema):
    """Shared authorization fields plus the stored PSYPRO renewal standing."""

    renewalStatus = String(required=False, allow_none=True, validate=OneOf(RENEWAL_STATUS_NAMES))


def install_psypact_authorization_schema() -> None:
    """Keep renewalStatus when an authorization is loaded. Callers do not read it."""
    from common_lambdas.schema.authorization import AuthorizationData

    AuthorizationData._record_schema = PsypactAuthorizationRecordSchema()  # noqa: SLF001
