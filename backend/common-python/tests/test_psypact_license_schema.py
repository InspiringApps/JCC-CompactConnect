# ruff: noqa: SLF001
import json
import os
import unittest
from datetime import date
from unittest.mock import Mock
from uuid import UUID

from marshmallow import ValidationError


def _configure_common_lambdas_for_tests():
    os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
    os.environ.setdefault('COMPACTS', '["psypact"]')
    os.environ.setdefault('JURISDICTIONS', json.dumps(['co', 'oh', 'ut']))
    os.environ.setdefault(
        'LICENSE_TYPES',
        json.dumps(
            {
                'psypact': [
                    {'name': 'Psychologist', 'abbreviation': 'psych'},
                    {'name': 'School Psychologist', 'abbreviation': 'schpsych'},
                ],
            },
        ),
    )


class TestPsypactLicenseSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _configure_common_lambdas_for_tests()

    def test_dump_generates_keys_without_npi(self):
        from common_lambdas.schema.license import PsypactLicenseSchema

        schema = PsypactLicenseSchema()
        dumped = schema.dump(
            {
                'type': 'license',
                'providerId': UUID('89a6377e-c3a5-40e5-bca5-317ec854c570'),
                'compact': 'psypact',
                'jurisdiction': 'co',
                'ssnLastFour': '1234',
                'licenseNumber': 'PSY-12345',
                'licenseType': 'Psychologist',
                'professionalType': 'Clinical',
                'givenName': 'Jane',
                'familyName': 'Doe',
                'dateOfIssuance': date.fromisoformat('2010-06-06'),
                'dateOfExpiration': date.fromisoformat('2025-04-04'),
                'dateOfBirth': date.fromisoformat('1985-06-06'),
                'homeAddressStreet1': '123 A St.',
                'homeAddressCity': 'Denver',
                'homeAddressState': 'co',
                'homeAddressPostalCode': '80202',
                'jurisdictionUploadedLicenseStatus': 'active',
                'jurisdictionUploadedCompactEligibility': 'eligible',
            },
        )

        self.assertNotIn('npi', dumped)
        self.assertEqual('psypact#PROVIDER#89a6377e-c3a5-40e5-bca5-317ec854c570', dumped['pk'])
        self.assertEqual('psypact#PROVIDER#license/co/psych#', dumped['sk'])
        self.assertEqual('PSY-12345', dumped['licenseNumber'])
        self.assertEqual('Clinical', dumped['professionalType'])

    def test_license_number_required(self):
        from common_lambdas.schema.license import PsypactLicenseSchema

        with self.assertRaises(ValidationError):
            PsypactLicenseSchema().load(
                {
                    'type': 'license',
                    'providerId': UUID('89a6377e-c3a5-40e5-bca5-317ec854c570'),
                    'compact': 'psypact',
                    'jurisdiction': 'co',
                    'ssnLastFour': '1234',
                    'licenseType': 'Psychologist',
                    'givenName': 'Jane',
                    'familyName': 'Doe',
                    'dateOfIssuance': '2010-06-06',
                    'dateOfExpiration': '2025-04-04',
                    'dateOfBirth': '1985-06-06',
                    'homeAddressStreet1': '123 A St.',
                    'homeAddressCity': 'Denver',
                    'homeAddressState': 'co',
                    'homeAddressPostalCode': '80202',
                    'jurisdictionUploadedLicenseStatus': 'active',
                    'jurisdictionUploadedCompactEligibility': 'eligible',
                    'licenseGSIPK': 'C#psypact#J#co',
                    'licenseGSISK': 'FN#doe#GN#jane',
                },
            )


class TestPsypactPrivilegeGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _configure_common_lambdas_for_tests()

    def test_privileges_use_selected_home_jurisdiction_not_most_recent_license(self):
        from common_lambdas import psypact_records
        from common_lambdas.data_model.schema.common import CompactEligibilityStatus
        from common_lambdas.psypact_records import PsypactProviderUserRecords

        provider_id = UUID('89a6377e-c3a5-40e5-bca5-317ec854c570')
        older_home = Mock(
            jurisdiction='co',
            licenseType='Psychologist',
            licenseTypeAbbreviation='psych',
            compactEligibility=CompactEligibilityStatus.ELIGIBLE,
            dateOfExpiration=date(2030, 4, 4),
            dateOfIssuance=date(2010, 6, 6),
            dateOfRenewal=None,
            providerId=provider_id,
        )
        newer_other_state = Mock(
            jurisdiction='oh',
            licenseType='Psychologist',
            licenseTypeAbbreviation='psych',
            compactEligibility=CompactEligibilityStatus.ELIGIBLE,
            dateOfExpiration=date(2030, 4, 4),
            dateOfIssuance=date(2024, 6, 6),
            dateOfRenewal=None,
            providerId=provider_id,
        )

        records = PsypactProviderUserRecords.__new__(PsypactProviderUserRecords)
        records._license_records = [older_home, newer_other_state]
        records._privilege_records = []
        records._military_affiliation_records = []
        records._privilege_update_records = []
        records.get_provider_record = Mock(
            return_value=Mock(compact='psypact', providerId=provider_id, currentHomeJurisdiction='co')
        )
        records.get_adverse_action_records_for_privilege = Mock(return_value=[])
        records.get_investigation_records_for_privilege = Mock(return_value=[])

        psypact_records.config.__dict__['live_compact_jurisdictions'] = {'psypact': ['co', 'oh', 'ut']}
        privileges = records.generate_privileges_for_provider()
        self.assertEqual({privilege['jurisdiction'] for privilege in privileges}, {'oh', 'ut'})
        self.assertTrue(all(privilege['licenseJurisdiction'] == 'co' for privilege in privileges))

    def test_expired_home_license_does_not_generate_privileges(self):
        from common_lambdas import psypact_records
        from common_lambdas.data_model.schema.common import CompactEligibilityStatus
        from common_lambdas.psypact_records import PsypactProviderUserRecords

        provider_id = UUID('89a6377e-c3a5-40e5-bca5-317ec854c570')
        expired_home = Mock(
            jurisdiction='co',
            licenseType='Psychologist',
            licenseTypeAbbreviation='psych',
            compactEligibility=CompactEligibilityStatus.ELIGIBLE,
            dateOfExpiration=date(2020, 1, 1),
            dateOfIssuance=date(2010, 6, 6),
            dateOfRenewal=None,
            providerId=provider_id,
        )

        records = PsypactProviderUserRecords.__new__(PsypactProviderUserRecords)
        records._license_records = [expired_home]
        records._privilege_records = []
        records._military_affiliation_records = []
        records._privilege_update_records = []
        records.get_provider_record = Mock(
            return_value=Mock(compact='psypact', providerId=provider_id, currentHomeJurisdiction='co')
        )

        psypact_records.config.__dict__['live_compact_jurisdictions'] = {'psypact': ['co', 'oh', 'ut']}
        self.assertEqual(records.generate_privileges_for_provider(), [])


class TestPsypactHomeJurisdictionValidation(unittest.TestCase):
    def test_other_and_unknown_are_rejected_without_a_license_lookup(self):
        import sys
        from pathlib import Path

        handler_dir = Path(__file__).resolve().parents[1] / 'lambdas' / 'provider-data-v1'
        if str(handler_dir) not in sys.path:
            sys.path.insert(0, str(handler_dir))

        _configure_common_lambdas_for_tests()
        from handlers.psypact_home_jurisdiction import _selected_jurisdiction_has_valid_license

        self.assertFalse(
            _selected_jurisdiction_has_valid_license(
                compact='psypact',
                provider_id='89a6377e-c3a5-40e5-bca5-317ec854c570',
                selected_jurisdiction='other',
            )
        )
        self.assertFalse(
            _selected_jurisdiction_has_valid_license(
                compact='psypact',
                provider_id='89a6377e-c3a5-40e5-bca5-317ec854c570',
                selected_jurisdiction='unknown',
            )
        )

    def test_expired_or_ineligible_license_is_rejected(self):
        import sys
        from pathlib import Path
        from unittest.mock import patch

        handler_dir = Path(__file__).resolve().parents[1] / 'lambdas' / 'provider-data-v1'
        if str(handler_dir) not in sys.path:
            sys.path.insert(0, str(handler_dir))

        _configure_common_lambdas_for_tests()
        from handlers.psypact_home_jurisdiction import _selected_jurisdiction_has_valid_license

        from common_lambdas.data_model.schema.common import CompactEligibilityStatus

        expired = Mock(
            jurisdiction='oh',
            compactEligibility=CompactEligibilityStatus.ELIGIBLE,
            dateOfExpiration=date(2020, 1, 1),
        )
        ineligible = Mock(
            jurisdiction='oh',
            compactEligibility=CompactEligibilityStatus.INELIGIBLE,
            dateOfExpiration=date(2030, 1, 1),
        )
        valid = Mock(
            jurisdiction='oh',
            compactEligibility=CompactEligibilityStatus.ELIGIBLE,
            dateOfExpiration=date(2030, 1, 1),
        )
        provider_records = Mock()

        with patch('handlers.psypact_home_jurisdiction.config') as mock_config:
            mock_config.data_client.get_provider_user_records.return_value = provider_records

            provider_records.get_license_records.return_value = [expired]
            self.assertFalse(
                _selected_jurisdiction_has_valid_license(
                    compact='psypact',
                    provider_id='89a6377e-c3a5-40e5-bca5-317ec854c570',
                    selected_jurisdiction='oh',
                )
            )

            provider_records.get_license_records.return_value = [ineligible]
            self.assertFalse(
                _selected_jurisdiction_has_valid_license(
                    compact='psypact',
                    provider_id='89a6377e-c3a5-40e5-bca5-317ec854c570',
                    selected_jurisdiction='oh',
                )
            )

            provider_records.get_license_records.return_value = [valid]
            self.assertTrue(
                _selected_jurisdiction_has_valid_license(
                    compact='psypact',
                    provider_id='89a6377e-c3a5-40e5-bca5-317ec854c570',
                    selected_jurisdiction='oh',
                )
            )


if __name__ == '__main__':
    unittest.main()
