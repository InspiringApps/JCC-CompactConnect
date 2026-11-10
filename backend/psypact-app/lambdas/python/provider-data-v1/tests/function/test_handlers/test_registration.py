import json
from datetime import datetime, timedelta
from functools import wraps
from unittest.mock import patch

from boto3.dynamodb.conditions import Key
from cc_common.provider_id import provider_id_for_email
from common_test.test_constants import DEFAULT_DATE_OF_UPDATE_TIMESTAMP
from moto import mock_aws

from .. import TstFunction

SIGNUP_EMAIL = 'Test@Example.com'
MOCK_IP_ADDRESS = '127.0.0.1'


def mock_delay_decorator(*args, **kwargs):  # noqa: ARG001 unused-argument
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)

        return decorated_function

    return decorator


@mock_aws
@patch('cc_common.config._Config.current_standard_datetime', datetime.fromisoformat(DEFAULT_DATE_OF_UPDATE_TIMESTAMP))
class TestProviderRegistration(TstFunction):
    def setUp(self):
        super().setUp()
        patch('cc_common.utils.delayed_function', mock_delay_decorator).start()
        from handlers.registration import register_provider

        self.register_provider = register_provider
        self.provider_id = provider_id_for_email(SIGNUP_EMAIL)

    def _event(self, body=None):
        with open('../common/tests/resources/api-event.json') as f:
            event = json.load(f)
        event['requestContext']['identity']['sourceIp'] = MOCK_IP_ADDRESS
        event['body'] = json.dumps({'email': SIGNUP_EMAIL} if body is None else body)
        return event

    def _provider_key(self):
        return {'pk': f'psypact#PROVIDER#{self.provider_id}', 'sk': 'psypact#PROVIDER'}

    def _cognito_user(self):
        return self.config.cognito_client.admin_get_user(
            UserPoolId=self.config.provider_user_pool_id, Username=SIGNUP_EMAIL
        )

    def _put_migrated_provider(self, *, registered_email=None):
        with open('../common/tests/resources/dynamo/provider.json') as f:
            provider_data = json.load(f)
        with open('../common/tests/resources/dynamo/license.json') as f:
            license_data = json.load(f)

        provider_data['providerId'] = self.provider_id
        provider_data['compact'] = 'psypact'
        provider_data['pk'] = f'psypact#PROVIDER#{self.provider_id}'
        provider_data['sk'] = 'psypact#PROVIDER'
        if registered_email is None:
            provider_data.pop('compactConnectRegisteredEmailAddress', None)
        else:
            provider_data['compactConnectRegisteredEmailAddress'] = registered_email

        license_data['providerId'] = self.provider_id
        license_data['pk'] = f'psypact#PROVIDER#{self.provider_id}'
        self.config.provider_table.put_item(Item=provider_data)
        self.config.provider_table.put_item(Item=license_data)
        return provider_data, license_data

    def test_new_email_creates_user_shell_and_invite(self):
        response = self.register_provider(self._event(), self.mock_context)

        self.assertEqual(200, response['statusCode'])
        self.assertEqual({'message': 'request processed'}, json.loads(response['body']))

        user = self._cognito_user()
        attributes = {item['Name']: item['Value'] for item in user['UserAttributes']}
        self.assertEqual('FORCE_CHANGE_PASSWORD', user['UserStatus'])
        self.assertEqual(self.provider_id, attributes['custom:providerId'])
        self.assertEqual('psypact', attributes['custom:compact'])
        self.assertEqual(SIGNUP_EMAIL, attributes['email'])
        self.assertEqual('true', attributes['email_verified'])

        shell = self.config.provider_table.get_item(Key=self._provider_key())['Item']
        self.assertEqual(
            {
                'pk': f'psypact#PROVIDER#{self.provider_id}',
                'sk': 'psypact#PROVIDER',
                'type': 'provider',
                'compact': 'psypact',
                'providerId': self.provider_id,
                'compactConnectRegisteredEmailAddress': SIGNUP_EMAIL,
                'dateOfUpdate': DEFAULT_DATE_OF_UPDATE_TIMESTAMP,
            },
            shell,
        )

    def test_migrated_email_reuses_provider_and_leaves_license(self):
        _, license_before = self._put_migrated_provider()

        response = self.register_provider(self._event(), self.mock_context)

        self.assertEqual(200, response['statusCode'])
        user = self._cognito_user()
        attributes = {item['Name']: item['Value'] for item in user['UserAttributes']}
        self.assertEqual(self.provider_id, attributes['custom:providerId'])

        provider = self.config.provider_table.get_item(Key=self._provider_key())['Item']
        self.assertEqual(SIGNUP_EMAIL, provider['compactConnectRegisteredEmailAddress'])
        self.assertEqual('oh', provider['currentHomeJurisdiction'])
        self.assertEqual('Björk', provider['givenName'])

        license_after = self.config.provider_table.get_item(
            Key={'pk': license_before['pk'], 'sk': license_before['sk']}
        )['Item']
        self.assertEqual(license_before, license_after)

        updates = self.config.provider_table.query(
            KeyConditionExpression=Key('pk').eq(provider['pk']) & Key('sk').begins_with('psypact#UPDATE')
        )['Items']
        self.assertEqual(1, len(updates))
        self.assertEqual('registration', updates[0]['updateType'])
        self.assertEqual(
            {'compactConnectRegisteredEmailAddress': SIGNUP_EMAIL},
            updates[0]['updatedValues'],
        )
        self.assertNotIn('compactConnectRegisteredEmailAddress', updates[0]['previous'])

    def test_live_account_does_not_create_a_second_user(self):
        self._put_migrated_provider(registered_email=SIGNUP_EMAIL)
        self._create_provider_cognito_user(
            email=SIGNUP_EMAIL,
            provider_id=self.provider_id,
            compact='psypact',
            password='Long-enough-password-1',  # noqa: S106 test-only password
        )

        with patch(
            'cc_common.email_service_client.EmailServiceClient.send_provider_multiple_registration_attempt_email'
        ) as mock_email:
            response = self.register_provider(self._event(), self.mock_context)

        self.assertEqual(200, response['statusCode'])
        self.assertEqual({'message': 'request processed'}, json.loads(response['body']))
        mock_email.assert_called_once_with(compact='psypact', provider_email=SIGNUP_EMAIL)
        users = self.config.cognito_client.list_users(UserPoolId=self.config.provider_user_pool_id)['Users']
        self.assertEqual(1, len(users))
        self.assertEqual('CONFIRMED', users[0]['UserStatus'])

    def test_stale_invite_is_resent(self):
        self._put_migrated_provider(registered_email=SIGNUP_EMAIL)
        self.config.cognito_client.admin_create_user(
            UserPoolId=self.config.provider_user_pool_id,
            Username=SIGNUP_EMAIL,
            UserAttributes=[
                {'Name': 'custom:compact', 'Value': 'psypact'},
                {'Name': 'custom:providerId', 'Value': self.provider_id},
                {'Name': 'email', 'Value': SIGNUP_EMAIL},
                {'Name': 'email_verified', 'Value': 'true'},
            ],
        )
        existing = self._cognito_user()
        self.assertEqual('FORCE_CHANGE_PASSWORD', existing['UserStatus'])

        later = existing['UserLastModifiedDate'] + timedelta(days=2)
        with (
            patch('cc_common.config._Config.current_standard_datetime', later),
            patch.object(
                self.config.cognito_client,
                'admin_create_user',
                wraps=self.config.cognito_client.admin_create_user,
            ) as create_user,
        ):
            response = self.register_provider(self._event(), self.mock_context)

        self.assertEqual(200, response['statusCode'])
        self.assertEqual({'message': 'request processed'}, json.loads(response['body']))
        create_user.assert_called_once_with(
            UserPoolId=self.config.provider_user_pool_id,
            Username=SIGNUP_EMAIL,
            MessageAction='RESEND',
        )

    def test_registration_rejects_extra_fields(self):
        response = self.register_provider(self._event({'email': SIGNUP_EMAIL, 'token': 'unused'}), self.mock_context)

        self.assertEqual(400, response['statusCode'])
        users = self.config.cognito_client.list_users(UserPoolId=self.config.provider_user_pool_id)['Users']
        self.assertEqual([], users)
