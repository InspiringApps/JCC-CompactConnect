import json
from uuid import UUID

from tests import TstLambdas

PROVIDER_ID = UUID('a3c1e7b2-4d58-4f0a-9c6e-2b7d1a0e5f34')


def _authorization_record(authorization_type: str, *, is_active: bool, expiration: str = '2027-03-01') -> dict:
    return {
        'pk': f'psypact#PROVIDER#{PROVIDER_ID}',
        'sk': f'psypact#PROVIDER#authorization/{authorization_type}#',
        'type': 'authorization',
        'dateOfUpdate': '2026-01-01T00:00:00+00:00',
        'providerId': str(PROVIDER_ID),
        'compact': 'psypact',
        'authorizationType': authorization_type,
        'dateOfExpiration': expiration,
        'isActive': is_active,
        'renewalStatus': 'Active',
    }


class TestApprovedAuthorizations(TstLambdas):
    def test_returns_active_apit_and_tap_and_omits_inactive(self):
        from cc_common.psypact_records import PsypactProviderUserRecords

        records = PsypactProviderUserRecords(
            [
                _authorization_record('TAP', is_active=True, expiration='2026-01-01'),
                _authorization_record('APIT', is_active=True),
                _authorization_record('APIT', is_active=False, expiration='2028-01-01'),
            ]
        )

        self.assertEqual(
            [
                {'authorizationType': 'APIT', 'dateOfExpiration': '2027-03-01', 'isActive': True},
                {'authorizationType': 'TAP', 'dateOfExpiration': '2026-01-01', 'isActive': True},
            ],
            records.approved_authorizations(),
        )

    def test_no_authorizations_returns_an_empty_list(self):
        from cc_common.psypact_records import PsypactProviderUserRecords

        self.assertEqual([], PsypactProviderUserRecords([]).approved_authorizations())


class TestAuthorizationResponseSchemas(TstLambdas):
    def setUp(self):
        super().setUp()
        with open('tests/resources/api/provider-detail-response.json') as provider_file:
            self.provider = json.load(provider_file)
        self.provider['authorizations'] = [
            {'authorizationType': 'APIT', 'dateOfExpiration': '2027-03-01', 'isActive': True}
        ]
        self.provider['privilegeJurisdictions'] = set(self.provider['privilegeJurisdictions'])

    def test_private_and_general_schemas_keep_authorizations(self):
        from cc_common.data_model.psypact_privilege_schema import (
            PsypactJccProviderGeneralResponseSchema,
            PsypactJccProviderReadPrivateResponseSchema,
            PsypactProviderGeneralResponseSchema,
            PsypactProviderReadPrivateResponseSchema,
        )

        for schema_cls in (
            PsypactJccProviderReadPrivateResponseSchema,
            PsypactJccProviderGeneralResponseSchema,
            PsypactProviderReadPrivateResponseSchema,
            PsypactProviderGeneralResponseSchema,
        ):
            with self.subTest(schema=schema_cls.__name__):
                loaded = schema_cls().load(self.provider)
                self.assertEqual(self.provider['authorizations'], loaded['authorizations'])

    def test_public_schemas_drop_authorizations(self):
        from cc_common.data_model.psypact_privilege_schema import (
            PsypactJccProviderPublicResponseSchema,
            PsypactProviderPublicResponseSchema,
        )
        from cc_common.data_model.schema.provider.api import ProviderPublicResponseSchema

        public_provider = dict(self.provider)
        public_provider['privileges'] = []
        public_provider['licenses'] = []
        for schema_cls in (
            PsypactJccProviderPublicResponseSchema,
            PsypactProviderPublicResponseSchema,
            ProviderPublicResponseSchema,
        ):
            with self.subTest(schema=schema_cls.__name__):
                loaded = schema_cls().load(public_provider)
                self.assertNotIn('authorizations', loaded)

    def test_staff_sanitizer_keeps_authorizations_from_the_extended_schema(self):
        from cc_common.utils import sanitize_provider_data_based_on_caller_scopes

        loaded = sanitize_provider_data_based_on_caller_scopes(
            compact='aslp',
            provider=self.provider,
            scopes={'openid', 'email', 'aslp/readGeneral', 'aslp/readPrivate'},
        )

        self.assertEqual(self.provider['authorizations'], loaded['authorizations'])
