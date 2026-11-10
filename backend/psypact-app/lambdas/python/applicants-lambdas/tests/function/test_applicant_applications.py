import json
import os
from unittest.mock import MagicMock

import applicant_applications
import boto3
from cc_common.applicants.application_state import StateName
from cc_common.applicants.application_transition_service import ApplicationTransitionService
from cc_common.applicants.application_workflow_client import ApplicationWorkflowClient
from cc_common.runtime import install
from moto import mock_aws

from tests import TstLambdas

COMPACT = 'psypact'
PROVIDER_ID = 'provider-1'
STATE_MACHINE_ARN = 'arn:aws:states:us-east-1:000000000000:stateMachine:ApplicationWorkflow'
_APPLICATIONS = '/v1/compacts/{compact}/applications'
_APPLICATION = _APPLICATIONS + '/{applicationId}'
_SECTION = _APPLICATION + '/sections/{section}'
_SUBMIT = _APPLICATION + '/submit'
_RESUBMIT = _APPLICATION + '/resubmit'
_HIDDEN = ('taskToken', 'taskTokenHash', 'executionArn', 'pendingAction', 'reopenLock', 'stateName')


def _event(method: str, resource: str, path: dict, body=None, provider_id: str = PROVIDER_ID, compact: str = COMPACT):
    event = {
        'httpMethod': method,
        'resource': resource,
        'headers': {'Content-Type': 'application/json', 'Origin': 'https://example.com'},
        'requestContext': {
            'resourcePath': resource,
            'authorizer': {
                'claims': {
                    'sub': 'applicant-sub',
                    'custom:compact': compact,
                    'custom:providerId': provider_id,
                }
            },
        },
        'pathParameters': path,
    }
    if body is not None:
        event['body'] = json.dumps(body)
    return event


@mock_aws
class TestApplicantApplications(TstLambdas):
    def setUp(self):  # noqa: N801 invalid-name
        super().setUp()
        os.environ.update(
            {
                'AWS_REGION': 'us-east-1',
                'ALLOWED_ORIGINS': '["https://example.com"]',
                'APPLICATION_STATE_MACHINE_ARN': STATE_MACHINE_ARN,
                'APPLICATION_SCHEDULE_GROUP_NAME': 'application-schedules',
                'APPLICATION_EXPIRY_FUNCTION_ARN': 'arn:aws:lambda:us-east-1:000000000000:function:expiry',
                'APPLICATION_SCHEDULER_ROLE_ARN': 'arn:aws:iam::000000000000:role/scheduler',
            }
        )
        install()
        from common_lambdas import config as config_module

        self.config = config_module.config
        for name in (
            'allowed_origins',
            'dynamodb_client',
            'application_client',
            'application_table',
            'stepfunctions_client',
            'application_workflow_client',
            'application_transition_service',
        ):
            self.config.__dict__.pop(name, None)
        boto3.client('dynamodb').create_table(
            TableName=os.environ['APPLICATION_TABLE_NAME'],
            BillingMode='PAY_PER_REQUEST',
            AttributeDefinitions=[
                {'AttributeName': 'pk', 'AttributeType': 'S'},
                {'AttributeName': 'sk', 'AttributeType': 'S'},
                {'AttributeName': 'applicantGSIPK', 'AttributeType': 'S'},
                {'AttributeName': 'applicantGSISK', 'AttributeType': 'S'},
            ],
            KeySchema=[
                {'AttributeName': 'pk', 'KeyType': 'HASH'},
                {'AttributeName': 'sk', 'KeyType': 'RANGE'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'applicantGSI',
                    'KeySchema': [
                        {'AttributeName': 'applicantGSIPK', 'KeyType': 'HASH'},
                        {'AttributeName': 'applicantGSISK', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
            ],
        )
        self.entered = 0
        self.enter_on_start = True
        self.advance_on_callback = True
        self.schedules = []
        self.sfn = MagicMock()
        self.sfn.start_execution.side_effect = self._on_start
        self.sfn.send_task_success.side_effect = self._on_success
        self.workflow = ApplicationWorkflowClient(STATE_MACHINE_ARN, self.sfn)
        self.config.application_transition_service = ApplicationTransitionService(
            self.config,
            workflow_client=self.workflow,
            schedule_creator=self._record_schedule,
            sleeper=lambda _seconds: None,
            poll_timeout_seconds=0,
            backoff_seconds=0,
        )

    def test_create_returns_the_application_without_workflow_internals(self):
        response = self._call('POST', _APPLICATIONS, {'compact': COMPACT}, {'types': ['apit'], 'isRenewal': False})

        self.assertEqual(200, response['statusCode'])
        body = json.loads(response['body'])
        self.assertEqual(['apit'], body['types'])
        self.assertFalse(body['isRenewal'])
        self.assertEqual('started', body['status'])
        self.assertIn('calculatedSectionStatusForApplicant', body['personalInformation'])
        self._assert_public(body)
        self.assertEqual(body['id'], self.schedules[0]['application_id'])

    def test_create_returns_202_when_the_execution_has_not_entered_a_state(self):
        self.enter_on_start = False

        response = self._call('POST', _APPLICATIONS, {'compact': COMPACT}, {'types': ['tap'], 'isRenewal': True})

        self.assertEqual(202, response['statusCode'])
        body = json.loads(response['body'])
        self.assertTrue(body['pending'])
        self.assertEqual('started', body['expectedStatus'])
        self.assertTrue(body['id'])
        self._assert_public(body)

    def test_list_returns_only_the_callers_applications(self):
        own = self._create()
        self._call(
            'PATCH',
            _SECTION,
            {'compact': COMPACT, 'applicationId': own['id'], 'section': 'personalInformation'},
            {'firstName': 'Ada'},
        )
        self._call(
            'POST',
            _APPLICATIONS,
            {'compact': COMPACT},
            {'types': ['tap'], 'isRenewal': True},
            provider_id='someone-else',
        )

        response = self._call('GET', _APPLICATIONS, {'compact': COMPACT})

        self.assertEqual(200, response['statusCode'])
        body = json.loads(response['body'])
        self.assertEqual([own['id']], [item['id'] for item in body['items']])
        listed = body['items'][0]
        self.assertEqual('Ada', listed['personalInformation']['firstName'])
        self.assertEqual('started', listed['status'])
        self.assertNotIn('providerId', listed)
        self.assertNotIn('stateName', listed)
        self._assert_public(listed)
        self.assertEqual(100, body['pagination']['pageSize'])
        self.assertIsNone(body['pagination']['lastKey'])

    def test_list_paginates_with_last_key(self):
        first = self._create()
        second = self._create()

        page = self._call('GET', _APPLICATIONS, {'compact': COMPACT}, query={'pageSize': '1'})

        self.assertEqual(200, page['statusCode'])
        body = json.loads(page['body'])
        self.assertEqual(1, len(body['items']))
        self.assertIsNotNone(body['pagination']['lastKey'])

        next_page = self._call(
            'GET',
            _APPLICATIONS,
            {'compact': COMPACT},
            query={'pageSize': '1', 'lastKey': body['pagination']['lastKey']},
        )
        self.assertEqual(200, next_page['statusCode'])
        rest = json.loads(next_page['body'])
        self.assertEqual(1, len(rest['items']))
        self.assertIsNone(rest['pagination']['lastKey'])
        self.assertEqual({first['id'], second['id']}, {body['items'][0]['id'], rest['items'][0]['id']})

    def test_get_is_limited_to_the_owning_practitioner(self):
        created = self._create()

        own = self._call('GET', _APPLICATION, {'compact': COMPACT, 'applicationId': created['id']})
        other = self._call(
            'GET',
            _APPLICATION,
            {'compact': COMPACT, 'applicationId': created['id']},
            provider_id='someone-else',
        )
        missing = self._call('GET', _APPLICATION, {'compact': COMPACT, 'applicationId': 'missing-application'})

        self.assertEqual(200, own['statusCode'])
        self.assertEqual(created['id'], json.loads(own['body'])['id'])
        self._assert_public(json.loads(own['body']))
        self.assertEqual(403, other['statusCode'])
        self.assertEqual(404, missing['statusCode'])

    def test_patch_merges_a_section_and_conflicts_return_409(self):
        created = self._create()
        application_id = created['id']
        path = {'compact': COMPACT, 'applicationId': application_id, 'section': 'personalInformation'}

        first = self._call('PATCH', _SECTION, path, {'firstName': 'Ada'})
        second = self._call('PATCH', _SECTION, path, {'lastName': 'Lovelace'})

        self.assertEqual(200, first['statusCode'])
        self.assertEqual(200, second['statusCode'])
        merged = json.loads(second['body'])
        self.assertEqual('Ada', merged['firstName'])
        self.assertEqual('Lovelace', merged['lastName'])
        self.assertIn('calculatedSectionStatusForApplicant', merged)
        self._assert_public(merged)

        self._enter(StateName.STAFF_REVIEW, application_id)
        conflict = self._call('PATCH', _SECTION, path, {'firstName': 'Augusta'})

        self.assertEqual(409, conflict['statusCode'])
        self.assertIn('message', json.loads(conflict['body']))
        unknown = self._call(
            'PATCH',
            _SECTION,
            {'compact': COMPACT, 'applicationId': application_id, 'section': 'not-a-section'},
            {'firstName': 'Ada'},
        )
        self.assertEqual(400, unknown['statusCode'])

    def test_submit_uses_a_generated_request_id_and_returns_the_new_status(self):
        created = self._create()

        response = self._call('POST', _SUBMIT, {'compact': COMPACT, 'applicationId': created['id']}, {})

        self.assertEqual(200, response['statusCode'])
        body = json.loads(response['body'])
        self.assertEqual('staff-review', body['status'])
        self._assert_public(body)
        output = json.loads(self.sfn.send_task_success.call_args.kwargs['output'])
        self.assertTrue(output['requestId'])
        self.assertEqual('SUBMIT', output['action'])

    def test_submit_keeps_the_callers_request_id_and_can_stay_pending(self):
        created = self._create()
        self.advance_on_callback = False

        response = self._call(
            'POST',
            _SUBMIT,
            {'compact': COMPACT, 'applicationId': created['id']},
            {'requestId': 'req-applicant-1'},
        )

        self.assertEqual(202, response['statusCode'])
        body = json.loads(response['body'])
        self.assertEqual('req-applicant-1', body['requestId'])
        self.assertEqual('staff-review', body['expectedStatus'])
        self.assertTrue(body['pending'])
        self._assert_public(body)
        output = json.loads(self.sfn.send_task_success.call_args.kwargs['output'])
        self.assertEqual('req-applicant-1', output['requestId'])

    def test_resubmit_returns_the_review_status(self):
        created = self._create()
        application_id = created['id']
        self._call('POST', _SUBMIT, {'compact': COMPACT, 'applicationId': application_id}, {'requestId': 'req-submit'})
        self._enter(StateName.AWAITING_APPLICANT_FROM_FIRST, application_id)

        response = self._call(
            'POST',
            _RESUBMIT,
            {'compact': COMPACT, 'applicationId': application_id},
            {'requestId': 'req-resubmit'},
        )

        self.assertEqual(200, response['statusCode'])
        body = json.loads(response['body'])
        self.assertEqual('first-review', body['status'])
        self._assert_public(body)
        output = json.loads(self.sfn.send_task_success.call_args.kwargs['output'])
        self.assertEqual('RESUBMIT', output['action'])
        self.assertEqual('req-resubmit', output['requestId'])

    def test_create_rejects_an_invalid_body_and_a_different_compact(self):
        invalid = self._call('POST', _APPLICATIONS, {'compact': COMPACT}, {'types': [], 'isRenewal': False})
        mismatch = self._call(
            'POST',
            _APPLICATIONS,
            {'compact': 'aslp'},
            {'types': ['apit'], 'isRenewal': False},
            compact='psypact',
        )

        self.assertEqual(400, invalid['statusCode'])
        self.assertEqual(403, mismatch['statusCode'])

    def _create(self) -> dict:
        response = self._call('POST', _APPLICATIONS, {'compact': COMPACT}, {'types': ['apit'], 'isRenewal': False})
        self.assertEqual(200, response['statusCode'], msg=response['body'])
        return json.loads(response['body'])

    def _call(
        self,
        method: str,
        resource: str,
        path: dict,
        body=None,
        provider_id: str = PROVIDER_ID,
        compact: str = COMPACT,
        query: dict | None = None,
    ):
        event = _event(method, resource, path, body, provider_id=provider_id, compact=compact)
        if query is not None:
            event['queryStringParameters'] = query
        return applicant_applications.applicant_applications(event, self.mock_context)

    def _assert_public(self, body: dict) -> None:
        encoded = json.dumps(body)
        for field_name in _HIDDEN:
            self.assertNotIn(field_name, encoded)

    def _on_start(self, **kwargs):
        body = json.loads(kwargs['input'])
        if self.enter_on_start:
            self._enter(StateName.STARTED, body['applicationId'])
        return {'executionArn': self.workflow.execution_arn(body['compact'], body['applicationId'], body['generation'])}

    def _on_success(self, **kwargs):
        if self.advance_on_callback:
            output = json.loads(kwargs['output'])
            state_name = StateName.STAFF_REVIEW if output['action'] == 'SUBMIT' else StateName.FIRST_REVIEW
            self._enter(state_name, self._latest_application_id())
        return {}

    def _record_schedule(self, **kwargs) -> None:
        self.schedules.append(kwargs)

    def _latest_application_id(self) -> str:
        return self.schedules[-1]['application_id']

    def _enter(self, state_name: StateName, application_id: str) -> None:
        self.entered += 1
        self.config.application_client.enter_state(
            COMPACT,
            application_id,
            execution_arn=self.workflow.execution_arn(COMPACT, application_id, 1),
            state_name=state_name,
            entered_time=f'2026-11-06T00:01:{self.entered:02d}+00:00',
            task_token=f'token-{self.entered}',
        )
