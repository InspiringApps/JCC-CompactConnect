from unittest.mock import MagicMock, patch

from tests import TstLambdas


class TestGetProviderInformation(TstLambdas):
    def test_reads_authorizations_from_the_installed_config(self):
        """The local config client returns records with no authorization method."""
        from handlers import get_provider_information

        installed_records = MagicMock()
        installed_records.generate_api_response_object.return_value = {'providerId': 'abc'}
        installed_records.approved_authorizations.return_value = [
            {'authorizationType': 'APIT', 'dateOfExpiration': '2027-01-01', 'isActive': True}
        ]
        installed_client = MagicMock()
        installed_client.get_provider_user_records.return_value = installed_records

        local_client = MagicMock()
        local_client.get_provider_user_records.return_value = MagicMock(spec=['generate_api_response_object'])

        with (
            patch('common_lambdas.config.config') as installed_config,
            patch('cc_common.config.config') as local_config,
        ):
            installed_config.data_client = installed_client
            local_config.data_client = local_client
            result = get_provider_information(compact='psypact', provider_id='abc')

        self.assertEqual(result['providerId'], 'abc')
        self.assertEqual(result['authorizations'][0]['authorizationType'], 'APIT')
        installed_client.get_provider_user_records.assert_called_once()
        local_client.get_provider_user_records.assert_not_called()
