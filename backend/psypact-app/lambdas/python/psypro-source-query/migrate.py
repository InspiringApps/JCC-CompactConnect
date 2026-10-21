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
from datetime import UTC, date, datetime

COMPACT = 'psypact'
LICENSE_TYPE = 'psychologist'
AUTHORIZATION_PROCESS_TYPES = {11: 'APIT', 12: 'TAP'}
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


def _record_schemas():
    """Schemas live in the shared layer, which is not on the path until runtime."""
    from cc_common.data_model.psypact_authorization_schema import PsypactAuthorizationRecordSchema
    from cc_common.data_model.schema.license.record import LicenseRecordSchema
    from cc_common.data_model.schema.provider.record import ProviderRecordSchema

    return ProviderRecordSchema(), LicenseRecordSchema(), PsypactAuthorizationRecordSchema()


def _dump_record(schema, data: dict) -> dict | None:
    from marshmallow import ValidationError

    try:
        dumped = schema.dump(data)
        schema.load(dumped)
    except ValidationError:
        return None
    return dumped


def _valid_email(email: str) -> bool:
    from marshmallow import ValidationError
    from marshmallow.validate import Email

    try:
        Email()(email)
    except ValidationError:
        return False
    return True


def _e164_us_phone(value: str | None) -> str | None:
    """Map NNN-NNN-NNNN to E.164. Other shapes are omitted."""
    if not value:
        return None
    digits = ''.join(character for character in value if character.isdigit())
    if len(digits) == 10:
        return f'+1{digits}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'+{digits}'
    return None


def _ssn_last_four(demographic: dict) -> str | None:
    value = _required_text(demographic, 'ssn')
    if value is None or len(value) != 4:
        return None
    return value


def _parse_declaration_time(value) -> datetime:
    if value is None or value == '':
        return datetime.min.replace(tzinfo=UTC)
    text = str(value).strip()
    if 'T' in text:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    date_part, _, rest = text.partition(' ')
    try:
        month, day, year = (int(part) for part in date_part.split('/'))
        clock = rest.split(' ')[0] if rest else '00:00:00'
        hour_text, minute_text, second_text = (clock.split(':') + ['0', '0'])[:3]
        return datetime(year, month, day, int(hour_text), int(minute_text), int(second_text), tzinfo=UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _is_validated(row: dict) -> bool:
    value = row.get('validated')
    if value is True:
        return True
    return str(value).strip().lower() == 'true'


def current_home_jurisdictions(rows: list[dict]) -> dict[int, str]:
    """Latest validated APIT or TAP home-state declaration for each user."""
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        if row.get('userId') is None or not _required_text(row, 'StateAbbreviation'):
            continue
        grouped.setdefault(int(row['userId']), []).append(row)
    chosen = {}
    for user_id, declarations in grouped.items():
        validated = [row for row in declarations if _is_validated(row)]
        if not validated:
            continue
        latest = max(validated, key=lambda row: _parse_declaration_time(row.get('UpdatedAt') or row.get('CreatedOn')))
        abbreviation = _required_text(latest, 'StateAbbreviation')
        if abbreviation:
            chosen[user_id] = abbreviation.lower()
    return chosen


def _license_preference(row: dict) -> tuple:
    standing = (_required_text(row, 'status') or '').lower()
    issue_text = _required_text(row, 'issueDate')
    issued = _as_date(issue_text) if issue_text else date.min
    try:
        entry_id = int(row['entryId']) if row.get('entryId') is not None else 0
    except (TypeError, ValueError):
        entry_id = 0
    return (1 if standing == 'active' else 0, issued, entry_id)


def _chosen_licenses(rows: list[dict]) -> list[dict]:
    """One license per jurisdiction. Every row is stored as the psychologist type."""
    by_jurisdiction: dict[str, dict] = {}
    for row in rows:
        jurisdiction = (_required_text(row, 'jurisdiction') or '').lower()
        if not jurisdiction:
            continue
        current = by_jurisdiction.get(jurisdiction)
        if current is None or _license_preference(row) > _license_preference(current):
            by_jurisdiction[jurisdiction] = row
    return list(by_jurisdiction.values())


def _optional(record: dict, key: str, target: dict, field: str) -> None:
    value = _required_text(record, key)
    if value:
        target[field] = value


def _authorization_item(schema, provider_id: str, authorization: dict) -> dict | None:
    data = {
        'providerId': uuid.UUID(provider_id),
        'compact': COMPACT,
        'authorizationType': authorization['authorizationType'],
        'dateOfExpiration': authorization['dateOfExpiration'],
        'isActive': True,
    }
    if authorization.get('renewalStatus'):
        data['renewalStatus'] = authorization['renewalStatus']
    return _dump_record(schema, data)


def _required_text(record: dict, key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _provider_item(
    schema,
    provider_id: str,
    demographic: dict,
    home_jurisdiction: str,
    current_home: str | None,
    expiration: date,
    has_active_home_license: bool,
) -> dict | None:
    given_name = _required_text(demographic, 'firstName')
    family_name = _required_text(demographic, 'lastName')
    birth_text = _required_text(demographic, 'birthDate')
    ssn_last_four = _ssn_last_four(demographic)
    if not all([given_name, family_name, birth_text, ssn_last_four]):
        return None
    standing = 'active' if has_active_home_license else 'inactive'
    eligibility = 'eligible' if has_active_home_license else 'ineligible'
    data = {
        'providerId': uuid.UUID(provider_id),
        'compact': COMPACT,
        'licenseJurisdiction': home_jurisdiction,
        'jurisdictionUploadedLicenseStatus': standing,
        'jurisdictionUploadedCompactEligibility': eligibility,
        'ssnLastFour': ssn_last_four,
        'givenName': given_name,
        'familyName': family_name,
        'dateOfExpiration': expiration,
        'dateOfBirth': _as_date(birth_text),
    }
    if current_home:
        data['currentHomeJurisdiction'] = current_home
    _optional(demographic, 'middleName', data, 'middleName')
    _optional(demographic, 'suffix', data, 'suffix')
    return _dump_record(schema, data)


def _license_item(
    schema,
    provider_id: str,
    license_row: dict,
    demographic: dict,
    expiration: date,
) -> dict | None:
    jurisdiction = (_required_text(license_row, 'jurisdiction') or '').lower()
    license_number = _required_text(license_row, 'licensureNumber')
    issue_text = _required_text(license_row, 'issueDate')
    given_name = _required_text(demographic, 'firstName')
    family_name = _required_text(demographic, 'lastName')
    birth_text = _required_text(demographic, 'birthDate')
    ssn_last_four = _ssn_last_four(demographic)
    street = _required_text(demographic, 'mailingAddress1')
    city = _required_text(demographic, 'mailingCity')
    state = _required_text(demographic, 'mailingState')
    postal_code = _required_text(demographic, 'mailingZip')
    if not all(
        [
            jurisdiction,
            license_number,
            issue_text,
            given_name,
            family_name,
            birth_text,
            ssn_last_four,
            street,
            city,
            state,
            postal_code,
        ]
    ):
        return None
    standing = 'active' if (_required_text(license_row, 'status') or '').lower() == 'active' else 'inactive'
    data = {
        'providerId': uuid.UUID(provider_id),
        'compact': COMPACT,
        'jurisdiction': jurisdiction,
        'licenseType': LICENSE_TYPE,
        'licenseNumber': license_number,
        'givenName': given_name,
        'familyName': family_name,
        'dateOfIssuance': _as_date(issue_text),
        'dateOfExpiration': expiration,
        'dateOfBirth': _as_date(birth_text),
        'homeAddressStreet1': street,
        'homeAddressCity': city,
        'homeAddressState': state,
        'homeAddressPostalCode': postal_code,
        'ssnLastFour': ssn_last_four,
        'jurisdictionUploadedLicenseStatus': standing,
        'jurisdictionUploadedCompactEligibility': 'eligible' if standing == 'active' else 'ineligible',
    }
    _optional(demographic, 'middleName', data, 'middleName')
    _optional(demographic, 'suffix', data, 'suffix')
    _optional(demographic, 'mailingAddress2', data, 'homeAddressStreet2')
    _optional(demographic, 'email', data, 'emailAddress')
    _optional(license_row, 'professionalType', data, 'professionalType')
    _optional(license_row, 'profession', data, 'profession')
    _optional(license_row, 'licenseTypeEntry', data, 'licenseTypeEntry')
    _optional(license_row, 'status', data, 'licenseStatusName')
    phone = _e164_us_phone(_required_text(demographic, 'primaryPhone'))
    if phone:
        data['phoneNumber'] = phone
    return _dump_record(schema, data)


def plan_migration(
    *,
    approval_rows: list[dict],
    home_rows: list[dict],
    demographics: dict[int, dict],
    emails: dict[int, str],
    licenses: list[dict],
    home_declarations: list[dict] | None = None,
) -> dict:
    """Return provider-table items for approved users, plus skip counts."""
    provider_schema, license_schema, authorization_schema = _record_schemas()
    declared_homes = current_home_jurisdictions(home_declarations or [])
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
        if email is None or not _valid_email(email):
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
            item = _authorization_item(authorization_schema, provider_id, authorization)
            if item is not None:
                items.append(item)
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
            provider = _provider_item(
                provider_schema,
                provider_id,
                demographic,
                home,
                declared_homes.get(user_id),
                expiration,
                active_home_license,
            )
            if provider is None:
                skipped_providers += 1
            else:
                items.append(provider)
        for license_row in _chosen_licenses(user_licenses):
            license_item = _license_item(license_schema, provider_id, license_row, demographic, expiration)
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
