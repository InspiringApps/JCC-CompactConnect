# ruff: noqa: N801, N815, ARG002  invalid-name unused-argument
"""PSYPACT extensions of the shared privilege response schemas.

Copied handlers import the provider response schemas by name and filter records
through them. ForgivingSchema drops any field those schemas do not declare, so
these subclasses are bound over the shared names when this module is imported.
"""

import common_lambdas.data_model.schema.privilege.api as privilege_api
import common_lambdas.data_model.schema.provider.api as provider_api
import common_lambdas.data_model.schema.provider.jcc_provider_api as jcc_provider_api
from common_lambdas.schema.authorization import AUTHORIZATION_TYPES
from marshmallow.fields import List, Nested, String
from marshmallow.validate import OneOf

_installed = False


def _authorization_type():
    return String(required=False, allow_none=False, validate=OneOf(AUTHORIZATION_TYPES))


class PsypactPrivilegeGeneralResponseSchema(privilege_api.PrivilegeGeneralResponseSchema):
    """Staff readGeneral privilege, plus the authorization that generated it."""

    privilegeAuthorizationType = _authorization_type()


class PsypactPrivilegeReadPrivateResponseSchema(privilege_api.PrivilegeReadPrivateResponseSchema):
    """Staff readPrivate privilege, plus the authorization that generated it."""

    privilegeAuthorizationType = _authorization_type()


class PsypactPrivilegePublicResponseSchema(privilege_api.PrivilegePublicResponseSchema):
    """Public privilege, plus the authorization that generated it."""

    privilegeAuthorizationType = _authorization_type()


def _privilege_list(schema_cls):
    return List(Nested(schema_cls(), required=False, allow_none=False))


class PsypactProviderGeneralResponseSchema(provider_api.ProviderGeneralResponseSchema):
    privileges = _privilege_list(PsypactPrivilegeGeneralResponseSchema)


class PsypactProviderReadPrivateResponseSchema(provider_api.ProviderReadPrivateResponseSchema):
    privileges = _privilege_list(PsypactPrivilegeReadPrivateResponseSchema)


class PsypactProviderPublicResponseSchema(provider_api.ProviderPublicResponseSchema):
    privileges = _privilege_list(PsypactPrivilegePublicResponseSchema)


class PsypactProviderOpenSearchDocumentSchema(provider_api.ProviderOpenSearchDocumentSchema):
    privileges = _privilege_list(PsypactPrivilegeGeneralResponseSchema)


class PsypactJccProviderGeneralResponseSchema(jcc_provider_api.ProviderGeneralResponseSchema):
    privileges = _privilege_list(PsypactPrivilegeGeneralResponseSchema)


class PsypactJccProviderReadPrivateResponseSchema(jcc_provider_api.ProviderReadPrivateResponseSchema):
    privileges = _privilege_list(PsypactPrivilegeReadPrivateResponseSchema)


class PsypactJccProviderPublicResponseSchema(jcc_provider_api.ProviderPublicResponseSchema):
    privileges = _privilege_list(PsypactPrivilegePublicResponseSchema)


def install_psypact_privilege_schemas() -> None:
    """Point copied handler imports at the PSYPACT privilege schemas."""
    global _installed
    if _installed:
        return

    privilege_api.PrivilegeGeneralResponseSchema = PsypactPrivilegeGeneralResponseSchema
    privilege_api.PrivilegeReadPrivateResponseSchema = PsypactPrivilegeReadPrivateResponseSchema
    privilege_api.PrivilegePublicResponseSchema = PsypactPrivilegePublicResponseSchema

    provider_api.ProviderGeneralResponseSchema = PsypactProviderGeneralResponseSchema
    provider_api.ProviderReadPrivateResponseSchema = PsypactProviderReadPrivateResponseSchema
    provider_api.ProviderPublicResponseSchema = PsypactProviderPublicResponseSchema
    provider_api.ProviderOpenSearchDocumentSchema = PsypactProviderOpenSearchDocumentSchema

    jcc_provider_api.ProviderGeneralResponseSchema = PsypactJccProviderGeneralResponseSchema
    jcc_provider_api.ProviderReadPrivateResponseSchema = PsypactJccProviderReadPrivateResponseSchema
    jcc_provider_api.ProviderPublicResponseSchema = PsypactJccProviderPublicResponseSchema
    _installed = True
