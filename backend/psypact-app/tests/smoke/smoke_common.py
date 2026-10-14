import base64
import hashlib
import hmac
import json
import os
import struct
import sys
import time

import boto3
import requests
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from config import config, logger


class SmokeTestFailureException(Exception):
    """Custom exception to raise when a smoke test fails."""

    def __init__(self, message):
        super().__init__(message)


provider_data_path = os.path.join('lambdas', 'python', 'staff-users')
common_lib_path = os.path.join('lambdas', 'python', 'common')
sys.path.append(provider_data_path)
sys.path.append(common_lib_path)

with open('cdk.json') as context_file:
    _context = json.load(context_file)['context']
JURISDICTIONS = _context['jurisdictions']
COMPACTS = _context['compacts']
LICENSE_TYPES = _context['license_types']

os.environ['COMPACTS'] = json.dumps(COMPACTS)
os.environ['JURISDICTIONS'] = json.dumps(JURISDICTIONS)
os.environ['LICENSE_TYPES'] = json.dumps(LICENSE_TYPES)

# We have to import this after we've added the common lib to our path and environment
from cc_common.data_model.provider_record_util import ProviderUserRecords  # noqa: E402
from cc_common.data_model.schema.user.record import UserRecordSchema  # noqa: E402

# Cognito advanced security rejects well-known test passwords with PasswordResetRequiredException.
_TEST_STAFF_USER_PASSWORD = 'PsypactSmokeStaff!2026k7'  # noqa: S105 test credential for test staff user
_TEMP_STAFF_PASSWORD = 'PsypactSmokeTemp!2026k7'  # noqa: S105 temporary password for creating test staff users
# Software-token secrets enrolled by this process. The staff and provider pools require MFA.
_totp_secrets: dict[str, str] = {}


def _totp_code(secret_b32: str, for_time: float | None = None) -> str:
    padded = secret_b32.strip().upper()
    padded += '=' * ((8 - len(padded) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    counter = int((time.time() if for_time is None else for_time) // 30)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f'{code % 1_000_000:06d}'


def _verify_software_token(session: str, secret: str) -> dict:
    last_error = None
    for offset in (0, 30, -30):
        try:
            return config.cognito_client.verify_software_token(
                Session=session,
                UserCode=_totp_code(secret, time.time() + offset),
            )
        except ClientError as error:
            last_error = error
            if error.response['Error']['Code'] not in {'EnableSoftwareTokenMFAException', 'CodeMismatchException'}:
                raise
    raise last_error


def _provider_totp_secret(email: str) -> str | None:
    if email != os.environ.get('CC_TEST_PROVIDER_USER_USERNAME'):
        return None
    return os.environ.get('CC_TEST_PROVIDER_TOTP_SECRET') or None


def _remember_provider_totp_secret(email: str, secret: str) -> None:
    """Keep the practitioner software-token secret for later smoke-test processes."""
    if email != os.environ.get('CC_TEST_PROVIDER_USER_USERNAME'):
        return
    os.environ['CC_TEST_PROVIDER_TOTP_SECRET'] = secret
    env_path = os.path.join(os.path.dirname(__file__), 'smoke_tests_env.json')
    with open(env_path) as env_file:
        env_vars = json.load(env_file)
    if env_vars.get('CC_TEST_PROVIDER_TOTP_SECRET') == secret:
        return
    env_vars['CC_TEST_PROVIDER_TOTP_SECRET'] = secret
    with open(env_path, 'w') as env_file:
        json.dump(env_vars, env_file, indent=2)
        env_file.write('\n')
    logger.info('Saved practitioner software-token secret to smoke_tests_env.json')


def _finish_cognito_mfa(response: dict, *, email: str, user_pool_id: str, client_id: str) -> dict:
    """Complete MFA setup or a software-token challenge so ADMIN_USER_PASSWORD_AUTH returns tokens."""
    challenge = response.get('ChallengeName')
    if challenge == 'MFA_SETUP':
        associated = config.cognito_client.associate_software_token(Session=response['Session'])
        secret = associated['SecretCode']
        _totp_secrets[email] = secret
        _remember_provider_totp_secret(email, secret)
        verified = _verify_software_token(associated['Session'], secret)
        return config.cognito_client.admin_respond_to_auth_challenge(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            ChallengeName='MFA_SETUP',
            Session=verified['Session'],
            ChallengeResponses={'USERNAME': email},
        )
    if challenge == 'SOFTWARE_TOKEN_MFA':
        secret = _totp_secrets.get(email) or _provider_totp_secret(email)
        if secret is None:
            raise SmokeTestFailureException(
                f'Cognito requires a software token for {email}, and this process does not have that secret'
            )
        return config.cognito_client.admin_respond_to_auth_challenge(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            ChallengeName='SOFTWARE_TOKEN_MFA',
            Session=response['Session'],
            ChallengeResponses={'USERNAME': email, 'SOFTWARE_TOKEN_MFA_CODE': _totp_code(secret)},
        )
    return response


def _create_staff_user_in_cognito(*, email: str) -> str:
    """
    Creates a staff user in Cognito and returns the user's sub.
    """

    def get_sub_from_attributes(user_attributes: list):
        for attribute in user_attributes:
            if attribute['Name'] == 'sub':
                return attribute['Value']
        raise ValueError('Failed to find user sub!')

    try:
        user_data = config.cognito_client.admin_create_user(
            UserPoolId=config.cognito_staff_user_pool_id,
            Username=email,
            UserAttributes=[{'Name': 'email', 'Value': email}],
            TemporaryPassword=_TEMP_STAFF_PASSWORD,
            # these are fake test addresses (e.g. @smokeTestFakeEmail.com); suppress Cognito's welcome
            # message so we don't send mail to (and bounce against) addresses that can't receive it
            MessageAction='SUPPRESS',
        )
        logger.info(f"Created staff user, '{email}'. Setting password.")
        # set this to simplify login flow for user
        config.cognito_client.admin_set_user_password(
            UserPoolId=config.cognito_staff_user_pool_id,
            Username=email,
            Password=_TEST_STAFF_USER_PASSWORD,
            Permanent=True,
        )
        logger.info(f"Set password for staff user, '{email}' in Cognito. New user data: {user_data}")
        return get_sub_from_attributes(user_data['User']['Attributes'])

    except ClientError as e:
        if e.response['Error']['Code'] == 'UsernameExistsException':
            logger.info(f"Staff user, '{email}', already exists in Cognito. Getting user data.")
            user_data = config.cognito_client.admin_get_user(
                UserPoolId=config.cognito_staff_user_pool_id, Username=email
            )
            return get_sub_from_attributes(user_data['UserAttributes'])

        raise e


def delete_test_staff_user(email: str, user_sub: str, compact: str):
    """Deletes a test staff user from Cognito.

    :param email: The email address of the staff user to delete
    :param user_sub: The user's sub ID
    :param compact: The compact identifier
    """
    try:
        logger.info(f"Deleting staff user from cognito, '{email}'")
        config.cognito_client.admin_delete_user(UserPoolId=config.cognito_staff_user_pool_id, Username=email)
        # now clean up the user record in DynamoDB
        pk = f'USER#{user_sub}'
        sk = f'COMPACT#{compact}'
        logger.info(f"Deleting staff user record from DynamoDB, PK: '{pk}', SK: '{sk}'")
        config.staff_users_dynamodb_table.delete_item(Key={'pk': pk, 'sk': sk})
        logger.info(f"Deleted staff user, '{email}', from Cognito and DynamoDB")
    except ClientError as e:
        logger.error(f"Failed to delete staff user data, '{email}': {str(e)}")
        raise e


def create_test_staff_user(*, email: str, compact: str, jurisdiction: str, permissions: dict):
    """Creates a test staff user in Cognito, stores their data in DynamoDB, and returns their user sub id.

    :param email: The email address of the staff user to create
    :param compact: The compact identifier
    :param jurisdiction: The jurisdiction identifier
    :param permissions: The permissions dictionary for the user
    :return: The staff user's sub ID
    """
    logger.info(f"Creating staff user, '{email}', in {compact}/{jurisdiction}")
    user_attributes = {'email': email, 'familyName': 'Dokes', 'givenName': 'Joe'}
    sub = _create_staff_user_in_cognito(email=email)
    schema = UserRecordSchema()
    config.staff_users_dynamodb_table.put_item(
        Item=schema.dump(
            {
                'type': 'user',
                'userId': sub,
                'compact': compact,
                'attributes': user_attributes,
                'permissions': permissions,
                'status': 'active',
            },
        ),
    )
    logger.info(f'Created staff user record in DynamoDB. User data: {user_attributes}')

    return sub


def get_user_tokens(email, password=_TEST_STAFF_USER_PASSWORD, is_staff=False):
    """
    Gets Cognito tokens for a user.
    {
        'IdToken': 'string',
        'AccessToken': 'string',
        'RefreshToken': 'string',
        'ExpiresIn': 123,
        'TokenType': 'string',
        'NewDeviceMetadata': {
            'DeviceKey': 'string',
            'DeviceGroupKey': 'string'
        }
    }
    """
    try:
        logger.info('Getting tokens for user: ' + email + ' user type: ' + ('staff' if is_staff else 'provider'))
        user_pool_id = config.cognito_staff_user_pool_id if is_staff else config.cognito_provider_user_pool_id
        client_id = config.cognito_staff_user_client_id if is_staff else config.cognito_provider_user_client_id
        response = config.cognito_client.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            AuthFlow='ADMIN_USER_PASSWORD_AUTH',
            AuthParameters={'USERNAME': email, 'PASSWORD': password},
        )
        response = _finish_cognito_mfa(response, email=email, user_pool_id=user_pool_id, client_id=client_id)

        return response['AuthenticationResult']

    except ClientError as e:
        logger.info(f'Failed to get tokens for user {email}: {str(e)}')
        raise e


def get_provider_user_auth_headers_cached():
    provider_token = os.environ.get('TEST_PROVIDER_USER_ID_TOKEN')
    if not provider_token:
        tokens = get_user_tokens(config.test_provider_user_username, config.test_provider_user_password, is_staff=False)
        os.environ['TEST_PROVIDER_USER_ID_TOKEN'] = tokens['IdToken']

    return {
        'Authorization': 'Bearer ' + os.environ['TEST_PROVIDER_USER_ID_TOKEN'],
    }


def get_staff_user_auth_headers(username: str, password: str = _TEST_STAFF_USER_PASSWORD):
    tokens = get_user_tokens(username, password, is_staff=True)
    return {
        'Authorization': 'Bearer ' + tokens['AccessToken'],
    }


def get_license_type_abbreviation(license_type: str):
    """
    Gets the abbreviation for a specific license type.
    """
    all_license_types = []
    for compact in LICENSE_TYPES:
        all_license_types.extend(LICENSE_TYPES[compact])
    return next((lt['abbreviation'] for lt in all_license_types if lt['name'] == license_type), None)


def get_api_base_url():
    return os.environ['CC_TEST_API_BASE_URL']


def get_provider_user_dynamodb_table():
    return boto3.resource('dynamodb').Table(os.environ['CC_TEST_PROVIDER_DYNAMO_TABLE_NAME'])


def get_rate_limiting_dynamodb_table():
    return boto3.resource('dynamodb').Table(os.environ['CC_TEST_RATE_LIMITING_DYNAMO_TABLE_NAME'])


def get_ssn_dynamodb_table():
    return boto3.resource('dynamodb').Table(os.environ['CC_TEST_SSN_DYNAMO_TABLE_NAME'])


def get_data_events_dynamodb_table():
    return boto3.resource('dynamodb').Table(os.environ['CC_TEST_DATA_EVENT_DYNAMO_TABLE_NAME'])


def get_provider_ssn_lambda_name():
    return os.environ['CC_TEST_GET_PROVIDER_SSN_LAMBDA_NAME']


def get_lambda_client():
    return boto3.client('lambda')


def load_smoke_test_env():
    with open(os.path.join(os.path.dirname(__file__), 'smoke_tests_env.json')) as env_file:
        env_vars = json.load(env_file)
        os.environ.update(env_vars)


def call_provider_users_me_endpoint():
    """Get the provider data from the GET '/v1/provider-users/me' endpoint.

    If a 403 response is received, the token will be refreshed and the request retried once.

    :return: The response body JSON
    :raises SmokeTestFailureException: If the request fails after retry
    """
    # Get the provider data from the GET '/v1/provider-users/me' endpoint.
    get_provider_data_response = requests.get(
        url=config.api_base_url + '/v1/provider-users/me', headers=get_provider_user_auth_headers_cached(), timeout=10
    )

    # If we get a 403, the token may have expired - refresh it and retry once
    if get_provider_data_response.status_code == 403 or get_provider_data_response.status_code == 401:
        logger.info('Received 403 response, refreshing provider user token and retrying...')
        # Clear the cached token to force a refresh
        if 'TEST_PROVIDER_USER_ID_TOKEN' in os.environ:
            del os.environ['TEST_PROVIDER_USER_ID_TOKEN']

        # Retry with fresh token
        get_provider_data_response = requests.get(
            url=config.api_base_url + '/v1/provider-users/me',
            headers=get_provider_user_auth_headers_cached(),
            timeout=10,
        )

    if get_provider_data_response.status_code != 200:
        raise SmokeTestFailureException(f'Failed to GET provider data. Response: {get_provider_data_response.json()}')
    # return the response body
    return get_provider_data_response.json()


def call_provider_details_endpoint(headers: dict, compact: str, provider_id: str) -> dict:
    """GET /v1/compacts/{compact}/providers/{provider_id} with staff auth headers."""
    url = f'{config.api_base_url}/v1/compacts/{compact}/providers/{provider_id}'
    response = requests.get(url=url, headers=headers, timeout=10)

    if response.status_code != 200:
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = response.text
        raise SmokeTestFailureException(f'Failed to GET provider details. Response: {body}')
    return response.json()


def wait_for_opensearch_sync() -> None:
    """Wait for provider table changes to propagate into OpenSearch."""
    seconds = 30
    logger.info(f'Waiting {seconds}s for changes to propagate in OpenSearch...')
    time.sleep(seconds)


def get_most_recently_issued_or_renewed_license(licenses: list[dict]) -> dict:
    """Select the license renewed most recently, otherwise the one issued most recently."""
    if not licenses:
        raise SmokeTestFailureException('No licenses found')

    def sort_key(license_record: dict) -> tuple[str, str]:
        return (license_record.get('dateOfRenewal') or '', license_record.get('dateOfIssuance') or '')

    return sorted(licenses, key=sort_key, reverse=True)[0]


def call_public_query_providers(
    compact: str,
    *,
    provider_id_filter: str,
    first_name_filter: str | None = None,
    last_name_filter: str | None = None,
    license_number_filter: str | None = None,
    page_size: int = 100,
    timeout: int = 30,
) -> list[dict]:
    """POST /v1/public/compacts/{compact}/providers/query and return rows for one provider."""
    url = f'{config.api_base_url}/v1/public/compacts/{compact}/providers/query'
    headers = {'Content-Type': 'application/json'}
    query_parameters: dict = {}
    if first_name_filter:
        query_parameters['givenName'] = first_name_filter
    if last_name_filter:
        query_parameters['familyName'] = last_name_filter
    if license_number_filter:
        query_parameters['licenseNumber'] = license_number_filter

    pagination_state: dict = {'pageSize': page_size}
    matching_license_rows: list[dict] = []

    for _page_index in range(500):
        request_body = {'query': query_parameters, 'pagination': pagination_state}
        response = requests.post(url=url, headers=headers, json=request_body, timeout=timeout)
        if response.status_code != 200:
            raise SmokeTestFailureException(f'Failed POST public query providers. Response: {response.json()}')
        page_response_body = response.json()

        for provider_license_row in page_response_body.get('providers') or []:
            if provider_id_filter and provider_license_row.get('providerId') == provider_id_filter:
                matching_license_rows.append(provider_license_row)

        last_pagination_key = (page_response_body.get('pagination') or {}).get('lastKey')
        if not last_pagination_key:
            break
        pagination_state = {**pagination_state, 'lastKey': last_pagination_key}

    return matching_license_rows


def call_public_get_provider(compact: str, provider_id: str, *, timeout: int = 30) -> dict:
    """GET /v1/public/compacts/{compact}/providers/{provider_id}."""
    url = f'{config.api_base_url}/v1/public/compacts/{compact}/providers/{provider_id}'
    response = requests.get(url=url, timeout=timeout)

    if response.status_code != 200:
        raise SmokeTestFailureException(f'Failed GET public provider. Response: {response.json()}')
    return response.json()


def get_all_provider_database_records(compact: str = 'psypact', provider_id: str | None = None):
    """Query every DynamoDB item stored for a provider.

    Privileges are generated at read time and are not stored here. Pass provider_id, or set
    CC_TEST_PROVIDER_ID, for the license-backed smoke provider.
    """
    if provider_id is None:
        provider_id = config.test_provider_id

    logger.info('Querying records for provider', provider_id=provider_id)
    items: list = []
    last_evaluated_key = None
    while True:
        pagination = {'ExclusiveStartKey': last_evaluated_key} if last_evaluated_key else {}
        query_result = config.provider_user_dynamodb_table.query(
            KeyConditionExpression=Key('pk').eq(f'{compact}#PROVIDER#{provider_id}'),
            **pagination,
        )
        items.extend(query_result.get('Items', []))
        last_evaluated_key = query_result.get('LastEvaluatedKey')
        if not last_evaluated_key:
            break

    return items


def get_provider_user_records(compact: str, provider_id: str) -> ProviderUserRecords:
    """
    Get all provider records from DynamoDB and return as ProviderUserRecords utility class.

    :param compact: The compact identifier
    :param provider_id: The provider's ID
    :return: ProviderUserRecords instance containing all records for this provider
    """
    # Query the provider database for all records
    resp = {'Items': []}
    last_evaluated_key = None
    while True:
        pagination = {'ExclusiveStartKey': last_evaluated_key} if last_evaluated_key else {}
        # Grab all records under the provider partition
        query_resp = config.provider_user_dynamodb_table.query(
            Select='ALL_ATTRIBUTES',
            KeyConditionExpression=Key('pk').eq(f'{compact}#PROVIDER#{provider_id}'),
            ConsistentRead=True,
            **pagination,
        )

        resp['Items'].extend(query_resp.get('Items', []))

        last_evaluated_key = query_resp.get('LastEvaluatedKey')
        if not last_evaluated_key:
            break

    return ProviderUserRecords(resp['Items'])
