import importlib.util
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[2] / 'migrate.py'
_SPEC = importlib.util.spec_from_file_location('psypro_source_migrate', _MODULE_PATH)
migrate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migrate)

UPDATED = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)


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
            updated_at=UPDATED,
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
        self.assertEqual('ada@example.com', by_type['provider']['emailAddress'])
        self.assertEqual('psypact#PROVIDER#license/co/doc-psych#', by_type['license']['sk'])
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
            updated_at=UPDATED,
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
            licenses=[],
            updated_at=UPDATED,
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
            updated_at=UPDATED,
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
            updated_at=UPDATED,
        )
        provider_id = migrate.provider_id_for_email('ada@example.com')
        self.assertEqual(1, result['skippedDuplicateEmails'])
        self.assertTrue(all(item['providerId'] == provider_id for item in result['items']))
        authorization_types = [item['authorizationType'] for item in result['items'] if item['type'] == 'authorization']
        self.assertEqual(['TAP'], authorization_types)
        self.assertEqual(['PSY-9'], [item['licenseNumber'] for item in result['items'] if item['type'] == 'license'])
