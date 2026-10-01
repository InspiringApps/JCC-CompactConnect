# Copied from backend/cosmetology-app/lambdas/python/custom-resources/tests/__init__.py

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
                'AWS_DEFAULT_REGION': 'us-east-1',
                'COMPACTS': '["cosm"]',
                'JURISDICTIONS': '["oh", "ky", "ne"]',
                'COMPACT_CONFIGURATION_TABLE_NAME': 'compact-configuration-table',
                'ENVIRONMENT_NAME': 'test',
            },
        )
        # Monkey-patch config object to be sure we have it based
        # on the env vars we set above
        import common_lambdas.config

        cls.config = common_lambdas.config._Config()  # noqa: SLF001 protected-access
        common_lambdas.config.config = cls.config
        cls.mock_context = MagicMock(name='MockLambdaContext', spec=LambdaContext)
