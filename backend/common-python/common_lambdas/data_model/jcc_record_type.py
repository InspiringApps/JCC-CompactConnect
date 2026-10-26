from enum import StrEnum


class ProviderRecordType(StrEnum):
    """Record types named by the extracted JCC DataClient methods.

    Cosmetology's ProviderRecordType has no stored privilege or military values.
    Compact-specific record types, such as an authorization, are not members here.
    """

    PROVIDER = 'provider'
    PROVIDER_UPDATE = 'providerUpdate'
    LICENSE = 'license'
    LICENSE_UPDATE = 'licenseUpdate'
    PRIVILEGE = 'privilege'
    PRIVILEGE_UPDATE = 'privilegeUpdate'
    MILITARY_AFFILIATION = 'militaryAffiliation'
    ADVERSE_ACTION = 'adverseAction'
    INVESTIGATION = 'investigation'
