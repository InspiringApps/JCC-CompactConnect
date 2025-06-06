import json
import os
from unittest import TestCase
from unittest.mock import MagicMock

from aws_lambda_powertools.utilities.typing import LambdaContext


class TstLambdas(TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update(
            {
                # Set to 'true' to enable debug logging
                'DEBUG': 'false',
                'ALLOWED_ORIGINS': '["https://example.org"]',
                'AWS_DEFAULT_REGION': 'us-east-1',
                'BULK_BUCKET_NAME': 'cc-license-data-bulk-bucket',
                'EVENT_BUS_NAME': 'license-data-events',
                'PROVIDER_TABLE_NAME': 'provider-table',
                'RATE_LIMITING_TABLE_NAME': 'rate-limiting-table',
                'SSN_TABLE_NAME': 'ssn-table',
                'COMPACT_CONFIGURATION_TABLE_NAME': 'compact-configuration-table',
                'ENVIRONMENT_NAME': 'test',
                'PROV_FAM_GIV_MID_INDEX_NAME': 'providerFamGivMid',
                'FAM_GIV_INDEX_NAME': 'famGiv',
                'LICENSE_GSI_NAME': 'licenseGSI',
                'PROVIDER_USER_POOL_ID': 'us-east-1-12345',
                'USERS_TABLE_NAME': 'staff-users-table',
                'EMAIL_NOTIFICATION_SERVICE_LAMBDA_NAME': 'email-notification-service-lambda',
                'PROV_DATE_OF_UPDATE_INDEX_NAME': 'providerDateOfUpdate',
                'SSN_INDEX_NAME': 'ssnIndex',
                'USER_POOL_ID': 'us-east-1-12345',
                'LICENSE_PREPROCESSING_QUEUE_URL': 'license-preprocessing-queue-url',
                'PROVIDER_USER_BUCKET_NAME': 'provider-user-bucket',
                'COMPACTS': '["aslp", "octp", "coun"]',
                'JURISDICTIONS': json.dumps(
                    [
                        'al',
                        'ak',
                        'az',
                        'ar',
                        'ca',
                        'co',
                        'ct',
                        'de',
                        'dc',
                        'fl',
                        'ga',
                        'hi',
                        'id',
                        'il',
                        'in',
                        'ia',
                        'ks',
                        'ky',
                        'la',
                        'me',
                        'md',
                        'ma',
                        'mi',
                        'mn',
                        'ms',
                        'mo',
                        'mt',
                        'ne',
                        'nv',
                        'nh',
                        'nj',
                        'nm',
                        'ny',
                        'nc',
                        'nd',
                        'oh',
                        'ok',
                        'or',
                        'pa',
                        'pr',
                        'ri',
                        'sc',
                        'sd',
                        'tn',
                        'tx',
                        'ut',
                        'vt',
                        'va',
                        'vi',
                        'wa',
                        'wv',
                        'wi',
                        'wy',
                    ]
                ),
                'LICENSE_TYPES': json.dumps(
                    {
                        'aslp': [
                            {'name': 'audiologist', 'abbreviation': 'aud'},
                            {'name': 'speech-language pathologist', 'abbreviation': 'slp'},
                        ],
                    },
                ),
            },
        )
        # Monkey-patch config object to be sure we have it based
        # on the env vars we set above
        import cc_common.config

        cls.config = cc_common.config._Config()  # noqa: SLF001 protected-access
        cc_common.config.config = cls.config
        cls.mock_context = MagicMock(name='MockLambdaContext', spec=LambdaContext)
