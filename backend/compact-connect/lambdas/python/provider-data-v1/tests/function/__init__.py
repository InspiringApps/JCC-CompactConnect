import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from glob import glob
from random import randint
from unittest.mock import patch

import boto3
from faker import Faker
from moto import mock_aws

from tests import TstLambdas

logger = logging.getLogger(__name__)
logging.basicConfig()
logger.setLevel(logging.DEBUG if os.environ.get('DEBUG', 'false') == 'true' else logging.INFO)


@mock_aws
class TstFunction(TstLambdas):
    """Base class to set up Moto mocking and create mock AWS resources for functional testing"""

    def setUp(self):  # noqa: N801 invalid-name
        super().setUp()

        self.build_resources()

        import cc_common.config

        cc_common.config.config = cc_common.config._Config()  # noqa: SLF001 protected-access
        self.config = cc_common.config.config

        self.addCleanup(self.delete_resources)

    def build_resources(self):
        self._bucket = boto3.resource('s3').create_bucket(Bucket=os.environ['BULK_BUCKET_NAME'])
        self.create_provider_table()
        self.create_ssn_table()
        self.create_rate_limiting_table()

        boto3.client('events').create_event_bus(Name=os.environ['EVENT_BUS_NAME'])

    def create_provider_table(self):
        self._provider_table = boto3.resource('dynamodb').create_table(
            AttributeDefinitions=[
                {'AttributeName': 'pk', 'AttributeType': 'S'},
                {'AttributeName': 'sk', 'AttributeType': 'S'},
                {'AttributeName': 'providerFamGivMid', 'AttributeType': 'S'},
                {'AttributeName': 'providerDateOfUpdate', 'AttributeType': 'S'},
                {'AttributeName': 'licenseGSIPK', 'AttributeType': 'S'},
                {'AttributeName': 'licenseGSISK', 'AttributeType': 'S'},
            ],
            TableName=os.environ['PROVIDER_TABLE_NAME'],
            KeySchema=[{'AttributeName': 'pk', 'KeyType': 'HASH'}, {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
            BillingMode='PAY_PER_REQUEST',
            GlobalSecondaryIndexes=[
                {
                    'IndexName': os.environ['PROV_FAM_GIV_MID_INDEX_NAME'],
                    'KeySchema': [
                        {'AttributeName': 'sk', 'KeyType': 'HASH'},
                        {'AttributeName': 'providerFamGivMid', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
                {
                    'IndexName': os.environ['PROV_DATE_OF_UPDATE_INDEX_NAME'],
                    'KeySchema': [
                        {'AttributeName': 'sk', 'KeyType': 'HASH'},
                        {'AttributeName': 'providerDateOfUpdate', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
                {
                    'IndexName': os.environ['LICENSE_GSI_NAME'],
                    'KeySchema': [
                        {'AttributeName': 'licenseGSIPK', 'KeyType': 'HASH'},
                        {'AttributeName': 'licenseGSISK', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
            ],
        )

    def create_ssn_table(self):
        self._ssn_table = boto3.resource('dynamodb').create_table(
            AttributeDefinitions=[
                {'AttributeName': 'pk', 'AttributeType': 'S'},
                {'AttributeName': 'sk', 'AttributeType': 'S'},
                {'AttributeName': 'providerIdGSIpk', 'AttributeType': 'S'},
            ],
            TableName=os.environ['SSN_TABLE_NAME'],
            KeySchema=[
                {'AttributeName': 'pk', 'KeyType': 'HASH'},
                {'AttributeName': 'sk', 'KeyType': 'RANGE'},
            ],
            BillingMode='PAY_PER_REQUEST',
            GlobalSecondaryIndexes=[
                {
                    'IndexName': os.environ['SSN_INDEX_NAME'],
                    'KeySchema': [
                        {'AttributeName': 'providerIdGSIpk', 'KeyType': 'HASH'},
                        {'AttributeName': 'sk', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
            ],
        )

    def create_rate_limiting_table(self):
        self._rate_limiting_table = boto3.resource('dynamodb').create_table(
            AttributeDefinitions=[
                {'AttributeName': 'pk', 'AttributeType': 'S'},
                {'AttributeName': 'sk', 'AttributeType': 'S'},
            ],
            TableName=os.environ['RATE_LIMITING_TABLE_NAME'],
            KeySchema=[{'AttributeName': 'pk', 'KeyType': 'HASH'}, {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
            BillingMode='PAY_PER_REQUEST',
        )

    def delete_resources(self):
        self._bucket.objects.delete()
        self._bucket.delete()
        self._provider_table.delete()
        self._ssn_table.delete()
        self._rate_limiting_table.delete()
        boto3.client('events').delete_event_bus(Name=os.environ['EVENT_BUS_NAME'])

    def _load_provider_data(self):
        """Use the canned test resources to load a basic provider to the DB"""
        test_resources = glob('../common/tests/resources/dynamo/*.json')

        def privilege_jurisdictions_to_set(obj: dict):
            if obj.get('type') == 'provider' and 'privilegeJurisdictions' in obj:
                obj['privilegeJurisdictions'] = set(obj['privilegeJurisdictions'])
            return obj

        for resource in test_resources:
            with open(resource) as f:
                if resource.endswith('user.json'):
                    # skip the staff user test data, as it is not stored in the provider table
                    continue
                record = json.load(f, object_hook=privilege_jurisdictions_to_set, parse_float=Decimal)

            logger.debug('Loading resource, %s: %s', resource, str(record))
            if record['type'] == 'provider-ssn':
                self._ssn_table.put_item(Item=record)
            else:
                self._provider_table.put_item(Item=record)

    def _generate_providers(self, *, home: str, privilege: str, start_serial: int, names: tuple[tuple[str, str]] = ()):
        """Generate 10 providers with one license and one privilege
        :param home: The jurisdiction for the license
        :param privilege: The jurisdiction for the privilege
        :param start_serial: Starting number for last portion of the provider's SSN
        :param names: A list of tuples, each containing a family name and given name
        """
        from cc_common.data_model.data_client import DataClient
        from handlers.ingest import ingest_license_message

        with open('../common/tests/resources/ingest/message.json') as f:
            ingest_message = json.load(f)

        name_faker = Faker(['en_US', 'ja_JP', 'es_MX'])
        data_client = DataClient(self.config)

        # Generate 10 providers, each with a license and a privilege
        for name_idx, ssn_serial in enumerate(range(start_serial, start_serial - 10, -1)):
            # So we can mutate top-level fields without messing up subsequent iterations
            ingest_message_copy = json.loads(json.dumps(ingest_message))

            # Use a requested name, if provided
            try:
                family_name, given_name = names[name_idx]
            except IndexError:
                family_name = name_faker.unique.last_name()
                given_name = name_faker.unique.first_name()
            ingest_message['detail']['familyName'] = family_name
            ingest_message['detail']['givenName'] = given_name
            ingest_message['detail']['middleName'] = name_faker.unique.first_name()

            ssn = f'{randint(100, 999)}-{randint(10, 99)}-{ssn_serial}'

            ingest_message_copy['detail'].update(
                {
                    'ssn': ssn,
                    'compact': 'aslp',
                    'jurisdiction': home,
                },
            )

            # This gives us some variation in dateOfUpdate values to sort by
            with patch(
                'cc_common.config._Config.current_standard_datetime',
                new_callable=lambda: datetime.now(tz=UTC).replace(microsecond=0) - timedelta(days=randint(1, 365)),
            ):
                ingest_license_message(
                    {'Records': [{'messageId': '123', 'body': json.dumps(ingest_message_copy)}]},
                    self.mock_context,
                )
            # Add a privilege
            provider_id = data_client.get_provider_id(compact='aslp', ssn=ssn)
            provider_record = data_client.get_provider(compact='aslp', provider_id=provider_id, detail=False)
            data_client.create_provider_privileges(
                compact='aslp',
                provider_id=provider_id,
                provider_record=provider_record,
                jurisdiction_postal_abbreviations=[privilege],
                license_expiration_date=date(2050, 6, 6),
                compact_transaction_id='1234567890',
                existing_privileges=[],
                license_type='speech-language pathologist',
                # This attestation id/version pair is defined in the 'privilege.json' file under the
                # common/tests/resources/dynamo directory
                attestations=[{'attestationId': 'jurisprudence-confirmation', 'version': '1'}],
            )
