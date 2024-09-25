import json

from moto import mock_aws
from tests.function import TstFunction

TEST_COMPACT = "aslp"
MOCK_SSN = "123-12-1234"
@mock_aws
class TestGetProvider(TstFunction):

    def _create_test_provider(self):
        from config import config
        provider_id = config.data_client.get_or_create_provider_id(compact=TEST_COMPACT, ssn=MOCK_SSN)

        return provider_id

    def test_get_provider(self):
        """
        Provider detail response
        """
        self._load_provider_data()

        from handlers.provider_users import get_provider

        with open('tests/resources/provider-user-api-event.json', 'r') as f:
            event = json.load(f)

        with open('tests/resources/api/provider-detail-response.json', 'r') as f:
            expected_provider = json.load(f)

        provider_id = self._create_test_provider()
        # set custom attributes in the cognito claims
        event['requestContext']['authorizer']['claims']['custom:providerId'] = provider_id
        event['requestContext']['authorizer']['claims']['custom:compact'] = TEST_COMPACT

        resp = get_provider(event, self.mock_context)

        self.assertEqual(200, resp['statusCode'])
        provider_data = json.loads(resp['body'])
        self.assertEqual(expected_provider, provider_data)
