# Copied from backend/cosmetology-app/lambdas/python/staff-users/tests/__init__.py

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
                'USER_POOL_ID': 'us-east-1-12345',
                'USERS_TABLE_NAME': 'provider-table',
                'COMPACT_CONFIGURATION_TABLE_NAME': 'compact-configuration-table',
                'FAM_GIV_INDEX_NAME': 'famGiv',
                'COMPACTS': '["cosm"]',
                'JURISDICTIONS': '["ne", "oh", "ky"]',
                'ENVIRONMENT_NAME': 'test',
            },
        )
        # Monkey-patch config object to be sure we have it based
        # on the env vars we set above
        import common_lambdas.config

        cls.config = common_lambdas.config._Config()  # noqa: SLF001 protected-access
        common_lambdas.config.config = cls.config
        cls.mock_context = MagicMock(name='MockLambdaContext', spec=LambdaContext)
