"""Build provider-table records from an approved PSYPRO snapshot.

A person is included when they have an APIT or TAP renewal with ApprovalDate
set. RenewalActivity.Status is not part of that filter. E.Passport and IPC are
not authorization types.

The source has no license expiration column. A migrated license and its
provider record use the earliest approved APIT or TAP expiration for that user.
A past expiration still migrates and does not by itself clear isActive.

RenewalProcessTypeState.Status is the stored authorization standing. Its
display name is written on the authorization and is not used to decide
isActive, license standing, or provider standing. GetTrueStatus is not applied.
providerId is a uuid5 of the lower-cased PSYPRO email. The same address
always maps to the same provider, license, and authorization keys, so a later
run replaces those items.
"""

import uuid
from datetime import date, datetime
from urllib.parse import quote

COMPACT = 'psypact'
AUTHORIZATION_PROCESS_TYPES = {11: 'APIT', 12: 'TAP'}
LICENSE_TYPE_ABBREVIATIONS = {
    'Doctoral Psychologist': 'doc-psych',
    'Masters Psychologist': 'ma-psych',
    'Psychologist': 'psych',
}
# RenewalStatus in the IA data dictionary. These are stored values, not the
# Expired 1/2/Permanently Expired values GetTrueStatus derives from DueOn.
RENEWAL_STATUS_NAMES = {
    0: 'Active',
    1: 'Inactive/Retired',
    2: 'Expired 1',
    3: 'Expired 2',
    4: 'Permanently Expired',
    5: 'Revoked',
    6: 'Voluntary Resign',
    7: 'Active*',
    8: 'Suspended',
    9: 'Abeyance',
    10: 'Deceased',
    11: 'Closed',
}


# Stable namespace so the same email always produces the same provider id.
EMAIL_PROVIDER_NAMESPACE = uuid.UUID('a3c1e7b2-4d58-4f0a-9c6e-2b7d1a0e5f34')


def provider_id_for_email(email: str) -> str:
    """UUID string from the stripped, lower-cased email."""
    return str(uuid.uuid5(EMAIL_PROVIDER_NAMESPACE, email.strip().lower()))


def migration_partition_key(provider_id: str) -> str:
    """Partition key shared by a provider and that provider's child records."""
    return f'{COMPACT}#PROVIDER#{provider_id}'


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _renewal_status_name(value) -> str | None:
    if value is None or value == '':
        return None
    try:
        return RENEWAL_STATUS_NAMES.get(int(value))
    except (TypeError, ValueError):
        return None


def approved_authorizations(rows: list[dict]) -> dict[int, list[dict]]:
    """Keep one current APIT and one current TAP per user.

    Inclusion is a non-null ApprovalDate and an expiration date. When a user
    has more than one approved row of the same type, the later expiration is
    the current credential, and its stored standing is the one that is kept.
    """
    chosen: dict[tuple[int, str], dict] = {}
    for row in rows:
        if not row.get('ApprovalDate') or not row.get('dateOfExpiration'):
            continue
        authorization_type = row.get('authorizationType')
        if authorization_type not in AUTHORIZATION_PROCESS_TYPES.values():
            continue
        user_id = int(row['UserId'])
        expiration = _as_date(row['dateOfExpiration'])
        key = (user_id, authorization_type)
        current = chosen.get(key)
        if current is not None and expiration <= current['dateOfExpiration']:
            continue
        chosen[key] = {
            'authorizationType': authorization_type,
            'dateOfExpiration': expiration,
            'renewalStatus': _renewal_status_name(row.get('renewalStatus')),
        }
    grouped: dict[int, list[dict]] = {}
    for (user_id, _authorization_type), authorization in sorted(chosen.items()):
        grouped.setdefault(user_id, []).append(authorization)
    return grouped


def home_jurisdictions(rows: list[dict], license_jurisdictions: dict[int, set[str]]) -> dict[int, str]:
    """Pick one home postal abbreviation per user, lowercase."""
    by_user: dict[int, set[str]] = {}
    for row in rows:
        abbreviation = (row.get('Abbreviation') or '').strip().lower()
        if not abbreviation:
            continue
        by_user.setdefault(int(row['UserId']), set()).add(abbreviation)
    chosen = {}
    for user_id, abbreviations in by_user.items():
        license_matches = abbreviations & license_jurisdictions.get(user_id, set())
        pool = license_matches or abbreviations
        chosen[user_id] = sorted(pool)[0]
    return chosen


def _name_key(family_name: str, given_name: str, middle_name: str = '') -> str:
    return '#'.join(
        (
            quote(family_name.lower()),
            quote(given_name.lower()),
            quote((middle_name or '').lower()),
        )
    )


def _authorization_item(provider_id: str, authorization: dict, updated_at: datetime) -> dict:
    authorization_type = authorization['authorizationType']
    item = {
        'pk': migration_partition_key(provider_id),
        'providerId': provider_id,
        'sk': f'{COMPACT}#PROVIDER#authorization/{authorization_type}#',
        'type': 'authorization',
        'compact': COMPACT,
        'authorizationType': authorization_type,
        'dateOfExpiration': authorization['dateOfExpiration'].isoformat(),
        'isActive': True,
        'dateOfUpdate': updated_at.isoformat(),
    }
    if authorization.get('renewalStatus'):
        item['renewalStatus'] = authorization['renewalStatus']
    return item


def _required_text(record: dict, key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _provider_item(
    provider_id: str,
    demographic: dict,
    home_jurisdiction: str,
    expiration: date,
    has_active_home_license: bool,
    updated_at: datetime,
) -> dict | None:
    given_name = _required_text(demographic, 'firstName')
    family_name = _required_text(demographic, 'lastName')
    birth_date = _required_text(demographic, 'birthDate')
    ssn_last_four = _required_text(demographic, 'ssn')
    street = _required_text(demographic, 'mailingAddress1')
    city = _required_text(demographic, 'mailingCity')
    state = _required_text(demographic, 'mailingState')
    postal_code = _required_text(demographic, 'mailingZip')
    if not all([given_name, family_name, birth_date, ssn_last_four, street, city, state, postal_code]):
        return None
    standing = 'active' if has_active_home_license else 'inactive'
    eligibility = 'eligible' if has_active_home_license else 'ineligible'
    item = {
        'pk': migration_partition_key(provider_id),
        'providerId': provider_id,
        'sk': f'{COMPACT}#PROVIDER',
        'type': 'provider',
        'compact': COMPACT,
        'licenseJurisdiction': home_jurisdiction,
        'jurisdictionUploadedLicenseStatus': standing,
        'jurisdictionUploadedCompactEligibility': eligibility,
        'ssnLastFour': ssn_last_four,
        'givenName': given_name,
        'familyName': family_name,
        'dateOfExpiration': expiration.isoformat(),
        'dateOfBirth': birth_date,
        'birthMonthDay': birth_date[5:10],
        'homeAddressStreet1': street,
        'homeAddressCity': city,
        'homeAddressState': state,
        'homeAddressPostalCode': postal_code,
        'providerFamGivMid': _name_key(family_name, given_name, demographic.get('middleName') or ''),
        'providerDateOfUpdate': updated_at.isoformat(),
        'dateOfUpdate': updated_at.isoformat(),
    }
    middle_name = _required_text(demographic, 'middleName')
    if middle_name:
        item['middleName'] = middle_name
    suffix = _required_text(demographic, 'suffix')
    if suffix:
        item['suffix'] = suffix
    email = _required_text(demographic, 'email')
    if email:
        item['emailAddress'] = email
    return item


def _license_item(
    provider_id: str,
    license_row: dict,
    demographic: dict,
    expiration: date,
    updated_at: datetime,
) -> dict | None:
    license_type = _required_text(license_row, 'licenseType')
    abbreviation = LICENSE_TYPE_ABBREVIATIONS.get(license_type or '')
    jurisdiction = (_required_text(license_row, 'jurisdiction') or '').lower()
    license_number = _required_text(license_row, 'licensureNumber')
    issue_date = _required_text(license_row, 'issueDate')
    if not all([abbreviation, jurisdiction, license_number, issue_date]):
        return None
    provider = _provider_item(
        provider_id,
        demographic,
        jurisdiction,
        expiration,
        has_active_home_license=True,
        updated_at=updated_at,
    )
    if provider is None:
        return None
    family_name = provider['familyName']
    given_name = provider['givenName']
    standing = 'active' if (_required_text(license_row, 'status') or '').lower() == 'active' else 'inactive'
    return {
        'pk': migration_partition_key(provider_id),
        'providerId': provider_id,
        'sk': f'{COMPACT}#PROVIDER#license/{jurisdiction}/{abbreviation}#',
        'type': 'license',
        'compact': COMPACT,
        'jurisdiction': jurisdiction,
        'licenseType': license_type,
        'licenseNumber': license_number,
        'dateOfIssuance': issue_date,
        'dateOfExpiration': expiration.isoformat(),
        'dateOfBirth': provider['dateOfBirth'],
        'givenName': given_name,
        'familyName': family_name,
        'ssnLastFour': provider['ssnLastFour'],
        'homeAddressStreet1': provider['homeAddressStreet1'],
        'homeAddressCity': provider['homeAddressCity'],
        'homeAddressState': provider['homeAddressState'],
        'homeAddressPostalCode': provider['homeAddressPostalCode'],
        'jurisdictionUploadedLicenseStatus': standing,
        'jurisdictionUploadedCompactEligibility': 'eligible' if standing == 'active' else 'ineligible',
        'licenseGSIPK': f'C#{COMPACT}#J#{jurisdiction}',
        'licenseGSISK': f'FN#{quote(family_name.lower())}#GN#{quote(given_name.lower())}',
        'dateOfUpdate': updated_at.isoformat(),
    }


def plan_migration(
    *,
    approval_rows: list[dict],
    home_rows: list[dict],
    demographics: dict[int, dict],
    emails: dict[int, str],
    licenses: list[dict],
    updated_at: datetime,
) -> dict:
    """Return provider-table items for approved users, plus skip counts."""
    authorizations = approved_authorizations(approval_rows)
    licenses_by_user: dict[int, list[dict]] = {}
    license_jurisdictions: dict[int, set[str]] = {}
    for license_row in licenses:
        user_id = int(license_row['userId'])
        licenses_by_user.setdefault(user_id, []).append(license_row)
        jurisdiction = (_required_text(license_row, 'jurisdiction') or '').lower()
        if jurisdiction:
            license_jurisdictions.setdefault(user_id, set()).add(jurisdiction)
    homes = home_jurisdictions(home_rows, license_jurisdictions)

    selected_users: dict[int, str] = {}
    email_owner: dict[str, int] = {}
    skipped_no_email = 0
    skipped_duplicate_emails = 0
    for user_id in authorizations:
        demographic = dict(demographics.get(user_id) or {})
        if emails.get(user_id):
            demographic['email'] = emails[user_id]
        email = _required_text(demographic, 'email')
        if email is None:
            skipped_no_email += 1
            continue
        normalized = email.lower()
        previous = email_owner.get(normalized)
        if previous is not None:
            skipped_duplicate_emails += 1
            if user_id < previous:
                continue
            selected_users.pop(previous, None)
        email_owner[normalized] = user_id
        selected_users[user_id] = provider_id_for_email(normalized)

    items = []
    skipped_providers = 0
    skipped_licenses = 0
    for user_id, user_authorizations in authorizations.items():
        provider_id = selected_users.get(user_id)
        if provider_id is None:
            continue
        expiration = min(entry['dateOfExpiration'] for entry in user_authorizations)
        for authorization in user_authorizations:
            items.append(_authorization_item(provider_id, authorization, updated_at))
        demographic = dict(demographics.get(user_id) or {})
        if emails.get(user_id):
            demographic['email'] = emails[user_id]
        home = homes.get(user_id)
        user_licenses = licenses_by_user.get(user_id, [])
        active_home_license = any(
            (_required_text(license_row, 'jurisdiction') or '').lower() == home
            and (_required_text(license_row, 'status') or '').lower() == 'active'
            for license_row in user_licenses
        )
        if home is None:
            skipped_providers += 1
        else:
            provider = _provider_item(provider_id, demographic, home, expiration, active_home_license, updated_at)
            if provider is None:
                skipped_providers += 1
            else:
                items.append(provider)
        for license_row in licenses_by_user.get(user_id, []):
            license_item = _license_item(provider_id, license_row, demographic, expiration, updated_at)
            if license_item is None:
                skipped_licenses += 1
            else:
                items.append(license_item)
    return {
        'items': items,
        'users': len(authorizations),
        'authorizations': sum(len(entries) for entries in authorizations.values()),
        'providers': sum(1 for item in items if item['type'] == 'provider'),
        'licenses': sum(1 for item in items if item['type'] == 'license'),
        'skippedProviders': skipped_providers,
        'skippedLicenses': skipped_licenses,
        'skippedNoEmail': skipped_no_email,
        'skippedDuplicateEmails': skipped_duplicate_emails,
    }
