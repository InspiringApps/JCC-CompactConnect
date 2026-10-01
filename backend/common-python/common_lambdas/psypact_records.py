from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from enum import StrEnum

from common_lambdas.config import config, logger
from common_lambdas.data_model.provider_record_util import (
    ProviderRecordType as CosmetologyProviderRecordType,
)
from common_lambdas.data_model.provider_record_util import (
    ProviderUserRecords,
    _license_sort_key,
)
from common_lambdas.data_model.schema.common import (
    ActiveInactiveStatus,
    CompactEligibilityStatus,
    InvestigationStatusEnum,
)
from common_lambdas.data_model.schema.fields import OTHER_JURISDICTION, UNKNOWN_JURISDICTION
from common_lambdas.data_model.schema.license import LicenseData
from common_lambdas.data_model.schema.military_affiliation import MilitaryAffiliationData
from common_lambdas.data_model.schema.privilege.jcc_data import PrivilegeData, PrivilegeUpdateData


class ProviderRecordType(StrEnum):
    """Cosmetology record types plus JCC stored privilege/military types used by account handlers."""

    PROVIDER = CosmetologyProviderRecordType.PROVIDER
    PROVIDER_UPDATE = CosmetologyProviderRecordType.PROVIDER_UPDATE
    LICENSE = CosmetologyProviderRecordType.LICENSE
    LICENSE_UPDATE = CosmetologyProviderRecordType.LICENSE_UPDATE
    ADVERSE_ACTION = CosmetologyProviderRecordType.ADVERSE_ACTION
    INVESTIGATION = CosmetologyProviderRecordType.INVESTIGATION
    PRIVILEGE = 'privilege'
    PRIVILEGE_UPDATE = 'privilegeUpdate'
    MILITARY_AFFILIATION = 'militaryAffiliation'


def license_is_unexpired(license_record: LicenseData) -> bool:
    expiration = license_record.dateOfExpiration
    if expiration is None:
        return False
    today = datetime.now(tz=UTC).date()
    if isinstance(expiration, datetime):
        expiration = expiration.date()
    return expiration >= today


class PsypactProviderUserRecords(ProviderUserRecords):
    """PSYPACT provider records: selected-home privilege generation and JCC account getters."""

    def __init__(self, provider_records: Iterable[dict]):
        super().__init__(provider_records)
        self._privilege_records: list[PrivilegeData] = []
        self._military_affiliation_records: list[MilitaryAffiliationData] = []
        self._privilege_update_records: list[PrivilegeUpdateData] = []
        for record in provider_records:
            record_type = record.get('type')
            if record_type == ProviderRecordType.PRIVILEGE:
                self._privilege_records.append(PrivilegeData.from_database_record(record))
            elif record_type == ProviderRecordType.MILITARY_AFFILIATION:
                self._military_affiliation_records.append(MilitaryAffiliationData.from_database_record(record))
            elif record_type == ProviderRecordType.PRIVILEGE_UPDATE:
                self._privilege_update_records.append(PrivilegeUpdateData.from_database_record(record))

    def get_privilege_records(
        self,
        filter_condition: Callable[[PrivilegeData], bool] | None = None,
    ) -> list[PrivilegeData]:
        return [record for record in self._privilege_records if filter_condition is None or filter_condition(record)]

    def get_military_affiliation_records(
        self, filter_condition: Callable[[MilitaryAffiliationData], bool] | None = None
    ) -> list[MilitaryAffiliationData]:
        return [
            record
            for record in self._military_affiliation_records
            if filter_condition is None or filter_condition(record)
        ]

    def selected_home_licenses(self) -> list[LicenseData]:
        """Licenses in the provider-selected currentHomeJurisdiction."""
        provider = self.get_provider_record()
        home = (provider.currentHomeJurisdiction or '').lower()
        if not home or home in {OTHER_JURISDICTION, UNKNOWN_JURISDICTION}:
            return []
        return [lic for lic in self._license_records if lic.jurisdiction.lower() == home and license_is_unexpired(lic)]

    def find_most_recent_licenses_for_each_license_type(self) -> list[LicenseData]:
        """Public/read home licenses come from currentHomeJurisdiction, not issuance dates."""
        by_type: dict[str, list[LicenseData]] = {}
        for lic in self.selected_home_licenses():
            by_type.setdefault(lic.licenseType, []).append(lic)
        selected: list[LicenseData] = []
        for licenses in by_type.values():
            selected.append(sorted(licenses, key=_license_sort_key, reverse=True)[0])
        return selected

    def generate_privileges_for_provider(self, include_inactive_privileges: bool = False) -> list[dict]:
        """
        Generate privilege dicts using the selected currentHomeJurisdiction as home.

        One privilege is produced for every live PSYPACT jurisdiction except home, matching
        Cosmetology's privilege dict shape. Home is the license(s) in currentHomeJurisdiction,
        not the most-recent license per type.
        """
        if not self._license_records:
            return []
        provider = self.get_provider_record()
        compact = provider.compact
        live_jurisdictions_for_compact = config.live_compact_jurisdictions.get(compact, [])

        if not live_jurisdictions_for_compact:
            logger.debug('no active jurisdictions found in environment.', compact=compact)
            return []

        home_licenses = self.selected_home_licenses()
        if not home_licenses:
            return []

        by_type: dict[str, list[LicenseData]] = {}
        for lic in home_licenses:
            by_type.setdefault(lic.licenseType, []).append(lic)

        selected_home_licenses_for_each_type: list[LicenseData] = []
        for _lt, licenses in by_type.items():
            sorted_licenses = sorted(licenses, key=_license_sort_key, reverse=True)
            selected_home_licenses_for_each_type.append(sorted_licenses[0])

        result: list[dict] = []
        for home_license in selected_home_licenses_for_each_type:
            is_eligible = home_license.compactEligibility == CompactEligibilityStatus.ELIGIBLE
            home_jurisdiction = home_license.jurisdiction.lower()
            license_type_abbr = home_license.licenseTypeAbbreviation

            for jurisdiction in live_jurisdictions_for_compact:
                if jurisdiction == home_jurisdiction:
                    continue
                privilege_aa = self.get_adverse_action_records_for_privilege(jurisdiction, license_type_abbr)
                privilege_unlifted = any(aa.effectiveLiftDate is None for aa in privilege_aa)
                inv_records = self.get_investigation_records_for_privilege(
                    jurisdiction, license_type_abbr, include_closed=False
                )
                if not is_eligible and not include_inactive_privileges and not privilege_aa and not inv_records:
                    logger.debug(
                        'Not returning a privilege for this jurisdiction because the home '
                        'license is not compact eligible and there are no matching privilege adverse '
                        'actions or open investigations.',
                        jurisdiction=jurisdiction,
                        home_jurisdiction=home_jurisdiction,
                        license_type_abbr=license_type_abbr,
                    )
                    continue
                privilege_dict = {
                    'type': 'privilege',
                    'administratorSetStatus': ActiveInactiveStatus.ACTIVE.value,
                    'providerId': str(provider.providerId),
                    'compact': compact,
                    'jurisdiction': jurisdiction,
                    'licenseJurisdiction': home_jurisdiction,
                    'licenseType': home_license.licenseType,
                    'dateOfExpiration': home_license.dateOfExpiration,
                    'status': ActiveInactiveStatus.ACTIVE.value
                    if is_eligible and not privilege_unlifted
                    else ActiveInactiveStatus.INACTIVE.value,
                    'adverseActions': [aa.to_dict() for aa in privilege_aa],
                    'investigations': [inv.to_dict() for inv in inv_records],
                }
                if privilege_dict.get('investigations'):
                    privilege_dict.update({'investigationStatus': InvestigationStatusEnum.UNDER_INVESTIGATION.value})

                result.append(privilege_dict)
        return result

    def generate_opensearch_documents(self) -> list[dict]:
        """Attach generated privileges to the selected currentHomeJurisdiction license documents."""
        if not self._license_records:
            return []

        provider_dict = self.get_provider_record().to_dict()
        all_privileges = self.generate_privileges_for_provider(include_inactive_privileges=True)

        home_licenses = {
            (home_license.jurisdiction.lower(), home_license.licenseType)
            for home_license in self.selected_home_licenses()
        }

        documents = []
        adverse_actions = [rec.to_dict() for rec in self.get_adverse_action_records()]
        for license_record in self.get_license_records():
            license_dict = license_record.to_dict()
            license_dict['adverseActions'] = [
                rec.to_dict()
                for rec in self.get_adverse_action_records_for_license(
                    license_record.jurisdiction, license_record.licenseTypeAbbreviation
                )
            ]
            license_dict['investigations'] = [
                rec.to_dict()
                for rec in self.get_investigation_records_for_license(
                    license_record.jurisdiction, license_record.licenseTypeAbbreviation
                )
            ]

            is_home_license_for_type = (
                license_record.jurisdiction.lower(),
                license_record.licenseType,
            ) in home_licenses
            license_privileges = (
                [p for p in all_privileges if p['licenseType'] == license_record.licenseType]
                if is_home_license_for_type
                else []
            )
            license_dict['mostRecentLicenseForType'] = is_home_license_for_type

            doc = dict(provider_dict)
            doc['licenses'] = [license_dict]
            doc['privileges'] = license_privileges
            doc['adverseActions'] = adverse_actions
            documents.append(doc)

        return documents
