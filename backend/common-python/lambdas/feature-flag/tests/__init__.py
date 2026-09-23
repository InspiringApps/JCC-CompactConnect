# Copied from backend/cosmetology-app/lambdas/python/feature-flag/tests/__init__.py

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
                'DEBUG': 'true',
                'ALLOWED_ORIGINS': '["https://example.org"]',
                'AWS_DEFAULT_REGION': 'us-east-1',
                'ENVIRONMENT_NAME': 'test',
                'COMPACTS': '["cosm"]',
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
            },
        )
        # Monkey-patch config object to be sure we have it based
        # on the env vars we set above
        import common_lambdas.config

        cls.config = common_lambdas.config._Config()  # noqa: SLF001 protected-access
        common_lambdas.config.config = cls.config
        cls.mock_context = MagicMock(name='MockLambdaContext', spec=LambdaContext)
