# Copied from backend/cosmetology-app/lambdas/python/staff-users/tests/unit/test_authorize_compact.py

import json

from aws_lambda_powertools.utilities.typing import LambdaContext

from tests import TstLambdas


class TestAuthorizeCompact(TstLambdas):
    def test_authorize_compact(self):
        from common_lambdas.data_model.schema.common import CCPermissionsAction
        from common_lambdas.utils import authorize_compact

        @authorize_compact(action=CCPermissionsAction.READ_GENERAL)
        def example_entrypoint(event: dict, context: LambdaContext):  # noqa: ARG001 unused-argument
            return {'body': 'Hurray!'}

        with open('tests/resources/api-event.json') as f:
            event = json.load(f)

        event['requestContext']['authorizer']['claims']['scope'] = 'openid email stuff cosm/readGeneral'
        event['pathParameters'] = {
            'compact': 'cosm',
        }

        self.assertEqual({'body': 'Hurray!'}, example_entrypoint(event, self.mock_context))

    def test_no_path_param(self):
        from common_lambdas.data_model.schema.common import CCPermissionsAction
        from common_lambdas.exceptions import CCInvalidRequestException
        from common_lambdas.utils import authorize_compact

        @authorize_compact(action=CCPermissionsAction.READ_GENERAL)
        def example_entrypoint(event: dict, context: LambdaContext):  # noqa: ARG001 unused-argument
            return {'body': 'Hurray!'}

        with open('tests/resources/api-event.json') as f:
            event = json.load(f)
        event['requestContext']['authorizer']['claims']['scope'] = 'openid email stuff cosm/readGeneral'
        event['pathParameters'] = {}

        with self.assertRaises(CCInvalidRequestException):
            example_entrypoint(event, self.mock_context)

    def test_no_authorizer(self):
        from common_lambdas.data_model.schema.common import CCPermissionsAction
        from common_lambdas.exceptions import CCUnauthorizedException
        from common_lambdas.utils import authorize_compact

        @authorize_compact(action=CCPermissionsAction.READ_GENERAL)
        def example_entrypoint(event: dict, context: LambdaContext):  # noqa: ARG001 unused-argument
            return {'body': 'Hurray!'}

        with open('tests/resources/api-event.json') as f:
            event = json.load(f)
        del event['requestContext']['authorizer']
        event['pathParameters'] = {'compact': 'cosm'}

        with self.assertRaises(CCUnauthorizedException):
            example_entrypoint(event, self.mock_context)

    def test_missing_scope(self):
        from common_lambdas.data_model.schema.common import CCPermissionsAction
        from common_lambdas.exceptions import CCAccessDeniedException
        from common_lambdas.utils import authorize_compact

        @authorize_compact(action=CCPermissionsAction.READ_GENERAL)
        def example_entrypoint(event: dict, context: LambdaContext):  # noqa: ARG001 unused-argument
            return {'body': 'Hurray!'}

        with open('tests/resources/api-event.json') as f:
            event = json.load(f)
        event['requestContext']['authorizer']['claims']['scope'] = 'openid email stuff'
        event['pathParameters'] = {'compact': 'cosm'}

        with self.assertRaises(CCAccessDeniedException):
            example_entrypoint(event, self.mock_context)
