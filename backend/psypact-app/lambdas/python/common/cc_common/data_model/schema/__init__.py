# ruff: noqa: F401
# We import all the record types with the package to ensure they are all registered
from common_lambdas.data_model.schema.adverse_action.record import AdverseActionRecordSchema
from common_lambdas.data_model.schema.attestation import AttestationRecordSchema
from common_lambdas.data_model.schema.military_affiliation.record import MilitaryAffiliationRecordSchema
from common_lambdas.data_model.schema.transaction.record import TransactionRecordSchema
from common_lambdas.data_model.schema.user.record import UserRecordSchema

from .compact.record import CompactRecordSchema
from .jurisdiction.record import JurisdictionRecordSchema
from .license.record import LicenseRecordSchema
from .privilege.record import PrivilegeRecordSchema
from .provider.record import ProviderRecordSchema
