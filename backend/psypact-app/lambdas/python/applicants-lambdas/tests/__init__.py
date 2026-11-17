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
                'DEBUG': 'false',
                'AWS_DEFAULT_REGION': 'us-east-1',
                'ENVIRONMENT_NAME': 'test',
                'APPLICATION_TABLE_NAME': 'application-table',
                'APPLICATION_STATUS_GSI_NAME': 'statusGSI',
                'APPLICATION_ACTOR_GSI_NAME': 'actorGSI',
                'APPLICATION_APPLICANT_GSI_NAME': 'applicantGSI',
                'COMPACTS': '["aslp", "octp", "coun", "psypact"]',
                'JURISDICTIONS': '["oh"]',
                'LICENSE_TYPES': json.dumps(
                    {'psypact': [{'name': 'psychologist', 'abbreviation': 'psy'}]},
                ),
            },
        )
        cls.mock_context = MagicMock(name='MockLambdaContext', spec=LambdaContext)
