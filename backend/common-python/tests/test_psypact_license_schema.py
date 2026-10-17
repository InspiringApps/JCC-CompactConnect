# ruff: noqa: SLF001
import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from marshmallow import ValidationError

_PSYPACT_COMMON = Path(__file__).resolve().parents[2] / 'psypact-app' / 'lambdas' / 'python' / 'common'


def _configure_common_lambdas_for_tests():
    if str(_PSYPACT_COMMON) not in sys.path:
        # Keep backend/common-python ahead of this entry. A local synth copy of
        # common_lambdas can sit beside cc_common and would otherwise shadow the source.
        sys.path.append(str(_PSYPACT_COMMON))
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
    from cc_common.runtime import install

    install()


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


PROVIDER_ID = UUID('89a6377e-c3a5-40e5-bca5-317ec854c570')


def _license_record(
    *,
    jurisdiction: str,
    expiration: date,
    eligibility,
    issued: date | None = None,
):
    return Mock(
        jurisdiction=jurisdiction,
        licenseType='Psychologist',
        licenseTypeAbbreviation='psych',
        compactEligibility=eligibility,
        dateOfExpiration=expiration,
        dateOfIssuance=issued or date(2010, 6, 6),
        dateOfRenewal=None,
        providerId=PROVIDER_ID,
    )


def _authorization(*, authorization_type: str, is_active: bool = True, expiration: date = date(2028, 1, 1)):
    return Mock(authorizationType=authorization_type, isActive=is_active, dateOfExpiration=expiration)


class TestPsypactPrivilegeGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _configure_common_lambdas_for_tests()

    def _records(self, licenses, authorizations, *, home: str = 'co'):
        from cc_common import psypact_records
        from cc_common.psypact_records import PsypactProviderUserRecords

        records = PsypactProviderUserRecords.__new__(PsypactProviderUserRecords)
        records._license_records = licenses
        records._authorization_records = authorizations
        records._privilege_records = []
        records._military_affiliation_records = []
        records._privilege_update_records = []
        records.get_provider_record = Mock(
            return_value=Mock(compact='psypact', providerId=PROVIDER_ID, currentHomeJurisdiction=home)
        )
        records.get_adverse_action_records_for_privilege = Mock(return_value=[])
        records.get_investigation_records_for_privilege = Mock(return_value=[])
        psypact_records.config.__dict__['live_compact_jurisdictions'] = {'psypact': ['co', 'oh', 'ut']}
        return records

    def test_valid_apit_authorization_generates_privileges_outside_home(self):
        from common_lambdas.data_model.schema.common import ActiveInactiveStatus, CompactEligibilityStatus

        records = self._records(
            [
                _license_record(
                    jurisdiction='co',
                    expiration=date(2030, 4, 4),
                    eligibility=CompactEligibilityStatus.ELIGIBLE,
                ),
                _license_record(
                    jurisdiction='oh',
                    expiration=date(2030, 4, 4),
                    eligibility=CompactEligibilityStatus.ELIGIBLE,
                    issued=date(2024, 6, 6),
                ),
            ],
            [_authorization(authorization_type='APIT')],
        )

        privileges = records.generate_privileges_for_provider()

        self.assertEqual({privilege['jurisdiction'] for privilege in privileges}, {'oh', 'ut'})
        self.assertTrue(all(privilege['licenseJurisdiction'] == 'co' for privilege in privileges))
        self.assertTrue(all(privilege['privilegeAuthorizationType'] == 'APIT' for privilege in privileges))
        self.assertTrue(all(privilege['status'] == ActiveInactiveStatus.ACTIVE.value for privilege in privileges))
        self.assertTrue(all(privilege['dateOfExpiration'] == date(2028, 1, 1) for privilege in privileges))

    def test_apit_and_tap_each_generate_a_privilege_per_state(self):
        from common_lambdas.data_model.schema.common import CompactEligibilityStatus

        records = self._records(
            [
                _license_record(
                    jurisdiction='co',
                    expiration=date(2030, 4, 4),
                    eligibility=CompactEligibilityStatus.ELIGIBLE,
                )
            ],
            [
                _authorization(authorization_type='APIT'),
                _authorization(authorization_type='TAP', expiration=date(2029, 6, 1)),
            ],
        )

        privileges = records.generate_privileges_for_provider()
        pairs = {(privilege['jurisdiction'], privilege['privilegeAuthorizationType']) for privilege in privileges}
        self.assertEqual(pairs, {('oh', 'APIT'), ('ut', 'APIT'), ('oh', 'TAP'), ('ut', 'TAP')})
        expirations = {
            privilege['privilegeAuthorizationType']: privilege['dateOfExpiration'] for privilege in privileges
        }
        self.assertEqual(expirations['APIT'], date(2028, 1, 1))
        self.assertEqual(expirations['TAP'], date(2029, 6, 1))

    def test_no_authorization_records_generate_no_privileges(self):
        from common_lambdas.data_model.schema.common import CompactEligibilityStatus

        records = self._records(
            [
                _license_record(
                    jurisdiction='co',
                    expiration=date(2030, 4, 4),
                    eligibility=CompactEligibilityStatus.ELIGIBLE,
                )
            ],
            [],
        )
        self.assertEqual(records.generate_privileges_for_provider(), [])

    def test_invalid_home_license_generates_no_active_privileges(self):
        from common_lambdas.data_model.schema.common import CompactEligibilityStatus

        eligible = CompactEligibilityStatus.ELIGIBLE
        ineligible = CompactEligibilityStatus.INELIGIBLE
        approved = [_authorization(authorization_type='APIT')]
        cases = [
            (
                [_license_record(jurisdiction='co', expiration=date(2020, 1, 1), eligibility=eligible)],
                'co',
            ),
            (
                [_license_record(jurisdiction='oh', expiration=date(2030, 4, 4), eligibility=eligible)],
                'co',
            ),
            (
                [_license_record(jurisdiction='co', expiration=date(2030, 4, 4), eligibility=ineligible)],
                'co',
            ),
        ]
        for licenses, home in cases:
            with self.subTest(
                home=home,
                expiration=licenses[0].dateOfExpiration,
                eligibility=licenses[0].compactEligibility,
            ):
                records = self._records(licenses, approved, home=home)
                privileges = records.generate_privileges_for_provider()
                self.assertFalse(any(privilege['status'] == 'active' for privilege in privileges))

    def test_inactive_or_expired_authorization_generates_no_active_privileges(self):
        from common_lambdas.data_model.schema.common import CompactEligibilityStatus

        home_license = [
            _license_record(
                jurisdiction='co',
                expiration=date(2030, 4, 4),
                eligibility=CompactEligibilityStatus.ELIGIBLE,
            )
        ]
        for authorization in (
            _authorization(authorization_type='TAP', is_active=False),
            _authorization(authorization_type='TAP', expiration=date(2020, 1, 1)),
        ):
            with self.subTest(is_active=authorization.isActive, expiration=authorization.dateOfExpiration):
                records = self._records(home_license, [authorization])
                privileges = records.generate_privileges_for_provider()
                self.assertFalse(any(privilege['status'] == 'active' for privilege in privileges))

    def test_invalid_authorization_still_shows_open_investigation(self):
        from common_lambdas.data_model.schema.common import ActiveInactiveStatus, CompactEligibilityStatus

        records = self._records(
            [
                _license_record(
                    jurisdiction='co',
                    expiration=date(2030, 4, 4),
                    eligibility=CompactEligibilityStatus.ELIGIBLE,
                )
            ],
            [_authorization(authorization_type='TAP', is_active=False)],
        )
        investigation = Mock()
        investigation.to_dict.return_value = {'type': 'investigation'}

        def investigations(jurisdiction, _license_type, include_closed=False):  # noqa: ARG001
            return [investigation] if jurisdiction == 'oh' else []

        records.get_investigation_records_for_privilege = Mock(side_effect=investigations)

        privileges = records.generate_privileges_for_provider()
        self.assertEqual(len(privileges), 1)
        self.assertEqual(privileges[0]['jurisdiction'], 'oh')
        self.assertEqual(privileges[0]['privilegeAuthorizationType'], 'TAP')
        self.assertEqual(privileges[0]['status'], ActiveInactiveStatus.INACTIVE.value)


class TestAuthorizationAndPrivilegeSchemas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _configure_common_lambdas_for_tests()

    def test_authorization_record_uses_practitioner_key(self):
        from common_lambdas.schema.authorization import AuthorizationRecordSchema

        dumped = AuthorizationRecordSchema().dump(
            {
                'providerId': PROVIDER_ID,
                'compact': 'psypact',
                'authorizationType': 'APIT',
                'dateOfExpiration': date(2030, 4, 4),
                'isActive': True,
            }
        )

        self.assertEqual(f'psypact#PROVIDER#{PROVIDER_ID}', dumped['pk'])
        self.assertEqual('psypact#PROVIDER#authorization/APIT#', dumped['sk'])
        self.assertEqual('authorization', dumped['type'])
        self.assertIs(dumped['isActive'], True)

    def test_privilege_response_schema_keeps_optional_authorization_type(self):
        from cc_common.data_model.psypact_privilege_schema import (
            PsypactPrivilegeGeneralResponseSchema,
            PsypactPrivilegePublicResponseSchema,
            PsypactPrivilegeReadPrivateResponseSchema,
        )

        from common_lambdas.data_model.schema.privilege import api as privilege_api

        privilege = {
            'type': 'privilege',
            'providerId': str(PROVIDER_ID),
            'compact': 'psypact',
            'jurisdiction': 'oh',
            'licenseJurisdiction': 'co',
            'licenseType': 'Psychologist',
            'dateOfExpiration': '2030-04-04',
            'administratorSetStatus': 'active',
            'status': 'active',
            'privilegeAuthorizationType': 'APIT',
        }
        for schema_cls in (
            PsypactPrivilegeGeneralResponseSchema,
            PsypactPrivilegeReadPrivateResponseSchema,
            PsypactPrivilegePublicResponseSchema,
        ):
            with self.subTest(schema=schema_cls.__name__):
                loaded = schema_cls().load(privilege)
                self.assertEqual('APIT', loaded['privilegeAuthorizationType'])
                omitted = dict(privilege)
                del omitted['privilegeAuthorizationType']
                self.assertNotIn('privilegeAuthorizationType', schema_cls().load(omitted))

        # The shared class itself stays unchanged. Package import binds the subclass
        # over the name copied handlers import.
        shared_schema = PsypactPrivilegeGeneralResponseSchema.__bases__[0]
        self.assertIs(privilege_api.PrivilegeGeneralResponseSchema, PsypactPrivilegeGeneralResponseSchema)
        self.assertNotIn('privilegeAuthorizationType', shared_schema().load(privilege))


class TestPsypactHomeJurisdictionValidation(unittest.TestCase):
    def test_other_and_unknown_are_rejected_without_a_license_lookup(self):
        import sys
        from pathlib import Path

        handler_dir = Path(__file__).resolve().parents[1] / 'lambdas' / 'provider-data-v1'
        if str(handler_dir) not in sys.path:
            sys.path.insert(0, str(handler_dir))

        _configure_common_lambdas_for_tests()
        from cc_common.psypact_home_jurisdiction import _selected_jurisdiction_has_valid_license

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
        from cc_common.psypact_home_jurisdiction import _selected_jurisdiction_has_valid_license

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

        with patch('cc_common.psypact_home_jurisdiction.config') as mock_config:
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
