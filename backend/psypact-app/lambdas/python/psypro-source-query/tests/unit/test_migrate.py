import importlib.util
import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path

_PSYPACT_APP = Path(__file__).resolve().parents[5]
for _entry in (
    _PSYPACT_APP.parent / 'common-python',
    _PSYPACT_APP / 'lambdas' / 'python' / 'common',
):
    if str(_entry) not in sys.path:
        sys.path.append(str(_entry))
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
os.environ['COMPACTS'] = '["psypact"]'
os.environ['JURISDICTIONS'] = json.dumps(['co', 'oh', 'ut', 'wa'])
os.environ['LICENSE_TYPES'] = json.dumps(
    {'psypact': [{'name': 'psychologist', 'abbreviation': 'psych'}]},
)

_MODULE_PATH = Path(__file__).resolve().parents[2] / 'migrate.py'
_SPEC = importlib.util.spec_from_file_location('psypro_source_migrate', _MODULE_PATH)
migrate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migrate)


def _demographic(user_id=7):
    return {
        'userId': user_id,
        'firstName': 'Ada',
        'lastName': 'Lovelace',
        'middleName': 'Ann',
        'birthDate': '1980-01-02',
        'ssn': '1234',
        'mailingAddress1': '1 Main St',
        'mailingCity': 'Denver',
        'mailingState': 'CO',
        'mailingZip': '80202',
    }


def _license_row():
    return {
        'userId': 7,
        'jurisdiction': 'CO',
        'licenseType': 'Doctoral Psychologist',
        'licensureNumber': 'PSY-1',
        'issueDate': '2019-05-01',
        'status': 'Active',
    }


class TestPsyproMigration(unittest.TestCase):
    def test_approval_date_includes_apit_and_tap_only(self):
        rows = [
            {
                'UserId': 7,
                'authorizationType': 'APIT',
                'Status': 0,
                'ApprovalDate': '2026-10-10',
                'dateOfExpiration': '2027-10-10',
                'renewalStatus': 5,
            },
            {
                'UserId': 7,
                'authorizationType': 'APIT',
                'ApprovalDate': '2026-01-01',
                'dateOfExpiration': '2026-01-01',
                'renewalStatus': 0,
            },
            {
                'UserId': 7,
                'authorizationType': 'TAP',
                'Status': 1,
                'dateOfExpiration': '2027-10-10',
            },
            {
                'UserId': 8,
                'authorizationType': 'EPassport',
                'ApprovalDate': '2026-10-10',
                'dateOfExpiration': '2027-10-10',
            },
        ]
        chosen = migrate.approved_authorizations(rows)
        self.assertEqual([7], list(chosen))
        self.assertEqual(
            [
                {
                    'authorizationType': 'APIT',
                    'dateOfExpiration': date(2027, 10, 10),
                    'renewalStatus': 'Revoked',
                }
            ],
            chosen[7],
        )

    def test_past_expiration_stays_active_and_keys_by_email(self):
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'APIT',
                    'ApprovalDate': '2019-01-01',
                    'dateOfExpiration': '2020-01-01',
                    'renewalStatus': 8,
                },
            ],
            home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
            demographics={7: _demographic()},
            emails={7: 'ada@example.com'},
            licenses=[_license_row()],
        )
        by_type = {item['type']: item for item in result['items']}
        provider_id = migrate.provider_id_for_email('ada@example.com')
        partition_key = f'psypact#PROVIDER#{provider_id}'
        self.assertEqual(provider_id, migrate.provider_id_for_email('Ada@Example.com'))
        self.assertTrue(by_type['authorization']['isActive'])
        self.assertEqual('Suspended', by_type['authorization']['renewalStatus'])
        self.assertEqual('2020-01-01', by_type['authorization']['dateOfExpiration'])
        self.assertEqual('2020-01-01', by_type['license']['dateOfExpiration'])
        self.assertEqual('active', by_type['license']['jurisdictionUploadedLicenseStatus'])
        self.assertEqual('psychologist', by_type['license']['licenseType'])
        self.assertEqual('ada@example.com', by_type['license']['emailAddress'])
        self.assertNotIn('emailAddress', by_type['provider'])
        self.assertEqual('01-02', by_type['provider']['birthMonthDay'])
        self.assertEqual('1234', by_type['provider']['ssnLastFour'])
        self.assertEqual('Ann', by_type['license']['middleName'])
        self.assertEqual('psypact#PROVIDER#license/co/psych#', by_type['license']['sk'])
        self.assertEqual('psypact#PROVIDER#authorization/APIT#', by_type['authorization']['sk'])
        for item in result['items']:
            self.assertEqual(partition_key, item['pk'])
            self.assertEqual(provider_id, item['providerId'])
            if item['type'] != 'authorization':
                self.assertNotIn('renewalStatus', item)

    def test_missing_standing_is_omitted(self):
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'TAP',
                    'ApprovalDate': '2026-10-11',
                    'dateOfExpiration': '2027-10-11',
                },
            ],
            home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
            demographics={7: _demographic()},
            emails={7: 'ada@example.com'},
            licenses=[_license_row()],
        )
        authorization = next(item for item in result['items'] if item['type'] == 'authorization')
        self.assertNotIn('renewalStatus', authorization)
        self.assertTrue(authorization['isActive'])

    def test_missing_identity_skips_provider_and_license(self):
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'TAP',
                    'ApprovalDate': '2026-10-11',
                    'dateOfExpiration': '2027-10-11',
                },
            ],
            home_rows=[],
            demographics={},
            emails={7: 'ada@example.com'},
            licenses=[_license_row()],
        )
        self.assertEqual(['authorization'], [item['type'] for item in result['items']])
        self.assertEqual(1, result['skippedProviders'])
        provider_id = migrate.provider_id_for_email('ada@example.com')
        self.assertEqual(f'psypact#PROVIDER#{provider_id}', result['items'][0]['pk'])
        self.assertEqual(provider_id, result['items'][0]['providerId'])

    def test_missing_email_writes_nothing(self):
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'TAP',
                    'ApprovalDate': '2026-10-11',
                    'dateOfExpiration': '2027-10-11',
                },
            ],
            home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
            demographics={7: _demographic()},
            emails={},
            licenses=[_license_row()],
        )
        self.assertEqual([], result['items'])
        self.assertEqual(1, result['skippedNoEmail'])

    def test_duplicate_email_keeps_the_higher_user_id(self):
        demographic = _demographic()
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'APIT',
                    'ApprovalDate': '2026-10-11',
                    'dateOfExpiration': '2027-10-11',
                },
                {
                    'UserId': 9,
                    'authorizationType': 'TAP',
                    'ApprovalDate': '2026-10-11',
                    'dateOfExpiration': '2027-10-11',
                },
            ],
            home_rows=[
                {'UserId': 7, 'Abbreviation': 'CO'},
                {'UserId': 9, 'Abbreviation': 'CO'},
            ],
            demographics={7: demographic, 9: _demographic(9)},
            emails={7: 'Ada@Example.com', 9: 'ada@example.com'},
            licenses=[_license_row(), {**_license_row(), 'userId': 9, 'licensureNumber': 'PSY-9'}],
        )
        provider_id = migrate.provider_id_for_email('ada@example.com')
        self.assertEqual(1, result['skippedDuplicateEmails'])
        self.assertTrue(all(item['providerId'] == provider_id for item in result['items']))
        authorization_types = [item['authorizationType'] for item in result['items'] if item['type'] == 'authorization']
        self.assertEqual(['TAP'], authorization_types)
        self.assertEqual(['PSY-9'], [item['licenseNumber'] for item in result['items'] if item['type'] == 'license'])

    def test_latest_validated_declaration_is_the_current_home(self):
        demographic = _demographic()
        demographic['primaryPhone'] = '303-555-0100'
        older = {**_license_row(), 'status': 'Inactive', 'licensureNumber': 'OLD', 'issueDate': '2010-01-01'}
        newer = {**_license_row(), 'status': 'Active', 'licensureNumber': 'NEW', 'issueDate': '2020-01-01'}
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'APIT',
                    'ApprovalDate': '2026-10-11',
                    'dateOfExpiration': '2027-10-11',
                },
            ],
            home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
            demographics={7: demographic},
            emails={7: 'ada@example.com'},
            licenses=[older, newer, {**newer, 'jurisdiction': 'WA', 'licensureNumber': 'WA-1'}],
            home_declarations=[
                {
                    'userId': 7,
                    'StateAbbreviation': 'OH',
                    'validated': 'True',
                    'UpdatedAt': '10/01/2020 00:00:00',
                },
                {
                    'userId': 7,
                    'StateAbbreviation': 'UT',
                    'validated': 'False',
                    'UpdatedAt': '10/01/2026 00:00:00',
                },
                {
                    'userId': 7,
                    'StateAbbreviation': 'WA',
                    'validated': 'true',
                    'CreatedOn': '10/10/2026 14:03:09 +00:00',
                },
            ],
        )
        provider = next(item for item in result['items'] if item['type'] == 'provider')
        licenses = [item for item in result['items'] if item['type'] == 'license']
        self.assertEqual('wa', provider['currentHomeJurisdiction'])
        self.assertEqual('+13035550100', next(item['phoneNumber'] for item in licenses if item['jurisdiction'] == 'co'))
        self.assertEqual(['NEW', 'WA-1'], sorted(item['licenseNumber'] for item in licenses))

    def test_later_issue_date_wins_over_an_earlier_active_license(self):
        active_older = {**_license_row(), 'status': 'Active', 'licensureNumber': 'OLD', 'issueDate': '2010-01-01'}
        inactive_newer = {
            **_license_row(),
            'status': 'Inactive',
            'licensureNumber': 'NEW',
            'issueDate': '2020-01-01',
            'entryId': 1,
        }
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'APIT',
                    'ApprovalDate': '2026-10-11',
                    'dateOfExpiration': '2027-10-11',
                },
            ],
            home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
            demographics={7: _demographic()},
            emails={7: 'ada@example.com'},
            licenses=[
                active_older,
                inactive_newer,
                {**active_older, 'jurisdiction': 'WA', 'licensureNumber': 'WA-1', 'issueDate': '2021-01-01'},
            ],
        )
        licenses = [item for item in result['items'] if item['type'] == 'license']
        colorado = next(item for item in licenses if item['jurisdiction'] == 'co')
        self.assertEqual('NEW', colorado['licenseNumber'])
        self.assertEqual('inactive', colorado['jurisdictionUploadedLicenseStatus'])
        self.assertEqual(['NEW', 'WA-1'], sorted(item['licenseNumber'] for item in licenses))

    def test_month_day_year_dates_are_stored_as_iso(self):
        demographic = _demographic()
        demographic['birthDate'] = '06/15/1980'
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'APIT',
                    'ApprovalDate': '06/15/2012',
                    'dateOfExpiration': '10/11/2027',
                },
            ],
            home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
            demographics={7: demographic},
            emails={7: 'ada@example.com'},
            licenses=[{**_license_row(), 'issueDate': '5/1/2019'}],
        )
        by_type = {item['type']: item for item in result['items']}
        self.assertEqual('1980-06-15', by_type['provider']['dateOfBirth'])
        self.assertEqual('06-15', by_type['provider']['birthMonthDay'])
        self.assertEqual('2019-05-01', by_type['license']['dateOfIssuance'])
        self.assertEqual('2027-10-11', by_type['authorization']['dateOfExpiration'])

    def test_unparseable_birth_date_skips_provider_and_license(self):
        demographic = _demographic()
        demographic['birthDate'] = 'not-a-date'
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'APIT',
                    'ApprovalDate': '2026-10-11',
                    'dateOfExpiration': '2027-10-11',
                },
            ],
            home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
            demographics={7: demographic},
            emails={7: 'ada@example.com'},
            licenses=[_license_row()],
        )
        self.assertEqual(['authorization'], [item['type'] for item in result['items']])
        self.assertEqual(1, result['skippedProviders'])
        self.assertEqual(1, result['skippedLicenses'])

    def test_psychologist_license_allows_the_authorization(self):
        result = migrate.plan_migration(
            approval_rows=[
                {
                    'UserId': 7,
                    'authorizationType': 'TAP',
                    'ApprovalDate': '2026-10-11',
                    'dateOfExpiration': '2027-10-11',
                },
            ],
            home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
            demographics={7: _demographic()},
            emails={7: 'ada@example.com'},
            licenses=[{**_license_row(), 'licenseType': 'Psychologist'}],
        )
        authorization_types = [item['authorizationType'] for item in result['items'] if item['type'] == 'authorization']
        self.assertEqual(['TAP'], authorization_types)

    def test_authorization_without_psychologist_license_fails_before_items(self):
        approval_rows = [
            {
                'UserId': 7,
                'authorizationType': 'APIT',
                'ApprovalDate': '2026-10-11',
                'dateOfExpiration': '2027-10-11',
            },
            {
                'UserId': 7,
                'authorizationType': 'TAP',
                'ApprovalDate': '2026-10-11',
                'dateOfExpiration': '2027-10-11',
            },
        ]
        with self.assertRaisesRegex(RuntimeError, r'user 7 \(APIT, TAP\)'):
            migrate.plan_migration(
                approval_rows=approval_rows,
                home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
                demographics={7: _demographic()},
                emails={7: 'ada@example.com'},
                licenses=[{**_license_row(), 'licenseType': 'Masters Psychologist'}],
            )
        with self.assertRaisesRegex(RuntimeError, r'user 7 \(APIT, TAP\)'):
            migrate.plan_migration(
                approval_rows=approval_rows,
                home_rows=[{'UserId': 7, 'Abbreviation': 'CO'}],
                demographics={7: _demographic()},
                emails={7: 'ada@example.com'},
                licenses=[],
            )
