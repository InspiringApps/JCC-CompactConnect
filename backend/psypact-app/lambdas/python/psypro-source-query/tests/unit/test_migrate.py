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

    def test_past_expiration_stays_active_and_omits_provider_id(self):
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
        partition_key = 'psypact#MIGRATION#7'
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
            self.assertNotIn('providerId', item)
            self.assertNotIn('ssnLastFour', item)
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
            emails={},
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
            emails={},
            licenses=[],
            updated_at=UPDATED,
        )
        self.assertEqual(['authorization'], [item['type'] for item in result['items']])
        self.assertEqual(1, result['skippedProviders'])
        self.assertEqual('psypact#MIGRATION#7', result['items'][0]['pk'])
