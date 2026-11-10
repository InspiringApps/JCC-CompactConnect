import json
import os
from unittest.mock import MagicMock
from uuid import uuid4

import boto3
import staff_applications
from cc_common.applicants.application_reopen_service import ApplicationReopenService
from cc_common.applicants.application_schedule_client import ApplicationScheduleClient
from cc_common.applicants.application_state import FIRST_AND_SECOND_REVIEWER_MUST_DIFFER, StateName
from cc_common.applicants.application_transition_service import ApplicationTransitionService
from cc_common.applicants.application_workflow_client import ApplicationWorkflowClient
from cc_common.runtime import install
from moto import mock_aws

from tests import TstLambdas

COMPACT = 'psypact'
PROVIDER_ID = 'provider-1'
ADMIN = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FIRST = '11111111-1111-1111-1111-111111111111'
SECOND = '22222222-2222-2222-2222-222222222222'
JURISDICTION_ONLY = '33333333-3333-3333-3333-333333333333'
STATE_MACHINE_ARN = 'arn:aws:states:us-east-1:000000000000:stateMachine:ApplicationWorkflow'
USERS_TABLE = 'users-table'
_APPLICATIONS = '/v1/compacts/{compact}/staff-users/applications'
_APPLICATION = _APPLICATIONS + '/{applicationId}'
_REVIEWERS = _APPLICATION + '/reviewers'
_SECTION_REVIEW = _APPLICATION + '/sections/{section}/review'
_TRANSITION = _APPLICATION + '/transition'
_ADMIN_STATUS = _APPLICATION + '/admin/status'
_REOPEN = _APPLICATION + '/reopen'
_HIDDEN = ('taskToken', 'taskTokenHash', 'executionArn', 'pendingAction', 'reopenLock')


def _event(method, resource, path, body=None, *, sub=ADMIN, scope='psypact/admin', query=None):
    event = {
        'httpMethod': method,
        'resource': resource,
        'headers': {'Content-Type': 'application/json', 'Origin': 'https://example.com'},
        'requestContext': {
            'resourcePath': resource,
            'authorizer': {'claims': {'sub': sub, 'scope': scope}},
        },
        'pathParameters': path,
        'queryStringParameters': query,
    }
    if body is not None:
        event['body'] = json.dumps(body)
    return event


@mock_aws
class TestStaffApplications(TstLambdas):
    def setUp(self):  # noqa: N801 invalid-name
        super().setUp()
        os.environ.update(
            {
                'AWS_REGION': 'us-east-1',
                'ALLOWED_ORIGINS': '["https://example.com"]',
                'USERS_TABLE_NAME': USERS_TABLE,
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
            'users_table',
            'user_client',
            'stepfunctions_client',
            'application_workflow_client',
            'application_transition_service',
            'application_reopen_service',
        ):
            self.config.__dict__.pop(name, None)
        self._create_tables()
        self._put_user(FIRST, 'First', 'Reviewer', compact_admin=True)
        self._put_user(SECOND, 'Second', 'Reviewer', compact_admin=True)
        self._put_user(ADMIN, 'Ada', 'Admin', compact_admin=True)
        self._put_user(JURISDICTION_ONLY, 'Jo', 'Jurisdiction', compact_admin=False)
        self.entered = 0
        self.advance_on_callback = True
        self.application_id = None
        self.sfn = MagicMock()
        self.sfn.start_execution.side_effect = self._on_start
        self.sfn.send_task_success.side_effect = self._on_success
        self.sfn.describe_execution.return_value = {'status': 'SUCCEEDED'}
        self.workflow = ApplicationWorkflowClient(STATE_MACHINE_ARN, self.sfn)
        self.config.application_transition_service = ApplicationTransitionService(
            self.config,
            workflow_client=self.workflow,
            schedule_creator=lambda **_kwargs: None,
            sleeper=lambda _seconds: None,
            poll_timeout_seconds=0,
            backoff_seconds=0,
        )
        self.config.application_reopen_service = ApplicationReopenService(
            self.config,
            workflow_client=self.workflow,
            transition_service=self.config.application_transition_service,
            schedule_creator=lambda **_kwargs: None,
            sleeper=lambda _seconds: None,
            poll_timeout_seconds=0,
            backoff_seconds=0,
        )
        self._delete_schedule = ApplicationScheduleClient.delete_schedule
        ApplicationScheduleClient.delete_schedule = lambda *_args, **_kwargs: None

    def tearDown(self):  # noqa: N801 invalid-name
        ApplicationScheduleClient.delete_schedule = self._delete_schedule
        super().tearDown()

    def test_jurisdiction_admin_is_denied_on_every_route(self):
        application_id = self._create()
        self._enter(StateName.STAFF_REVIEW, application_id)
        path = {'compact': COMPACT, 'applicationId': application_id}
        calls = [
            ('GET', _APPLICATIONS, {'compact': COMPACT}, None, {'status': 'started'}),
            ('GET', _APPLICATION, path, None, None),
            ('PUT', _REVIEWERS, path, {'firstReviewerSub': FIRST}, None),
            (
                'PUT',
                _SECTION_REVIEW,
                {**path, 'section': 'personalInformation'},
                {'sectionStatus': 'approved'},
                None,
            ),
            ('POST', _TRANSITION, path, {'action': 'REVIEWERS_ASSIGNED', 'requestId': 'req-deny'}, None),
            (
                'POST',
                _ADMIN_STATUS,
                path,
                {'targetState': 'StaffReview', 'requestId': 'req-deny-status'},
                None,
            ),
            ('POST', _REOPEN, path, {'requestId': 'req-deny-reopen', 'reason': 'again'}, None),
        ]
        for method, resource, route_path, body, query in calls:
            response = self._call(
                method,
                resource,
                route_path,
                body,
                query=query,
                scope='oh/psypact.admin',
            )
            self.assertEqual(403, response['statusCode'], msg=resource)

    def test_get_returns_reviewers_and_hides_workflow_internals(self):
        application_id = self._staff_review()
        assigned = self._call(
            'PUT',
            _REVIEWERS,
            {'compact': COMPACT, 'applicationId': application_id},
            {'firstReviewerSub': FIRST},
        )
        self.assertEqual(200, assigned['statusCode'], msg=assigned['body'])

        response = self._call('GET', _APPLICATION, {'compact': COMPACT, 'applicationId': application_id})

        self.assertEqual(200, response['statusCode'])
        body = json.loads(response['body'])
        self.assertEqual(application_id, body['id'])
        self.assertEqual('StaffReview', body['stateName'])
        self.assertEqual(FIRST, body['firstReviewerSub'])
        self.assertEqual('First', body['firstReviewerFirstName'])
        self.assertIn('reviews', body)
        self._assert_staff(body)
        missing = self._call('GET', _APPLICATION, {'compact': COMPACT, 'applicationId': 'missing-application'})
        self.assertEqual(404, missing['statusCode'])

    def test_list_uses_the_status_index_unless_mine_is_set(self):
        application_id = self._staff_review()
        self._assign(application_id, firstReviewerSub=FIRST, secondReviewerSub=SECOND, finalReviewerSub=FIRST)
        self._enter(StateName.FIRST_REVIEW, application_id)

        by_status = self._call('GET', _APPLICATIONS, {'compact': COMPACT}, query={'status': 'first-review'})
        by_old_status = self._call('GET', _APPLICATIONS, {'compact': COMPACT}, query={'status': 'staff-review'})
        mine = self._call('GET', _APPLICATIONS, {'compact': COMPACT}, query={'mine': 'true'}, sub=FIRST)
        someone_else = self._call('GET', _APPLICATIONS, {'compact': COMPACT}, query={'mine': 'true'}, sub=ADMIN)
        invalid = self._call('GET', _APPLICATIONS, {'compact': COMPACT}, query={'status': 'not-a-status'})

        self.assertEqual(200, by_status['statusCode'])
        listed = json.loads(by_status['body'])
        self.assertEqual([application_id], [item['id'] for item in listed['items']])
        summary = listed['items'][0]
        self.assertEqual('first-review', summary['status'])
        self.assertEqual('FirstReview', summary['stateName'])
        self.assertEqual(PROVIDER_ID, summary['providerId'])
        self.assertEqual(['apit'], summary['types'])
        self.assertEqual(FIRST, summary['actorSub'])
        self.assertNotIn('taskToken', json.dumps(summary))
        self.assertIn('pagination', listed)
        self.assertEqual([], json.loads(by_old_status['body'])['items'])
        self.assertEqual([application_id], [item['id'] for item in json.loads(mine['body'])['items']])
        self.assertEqual([], json.loads(someone_else['body'])['items'])
        self.assertEqual(400, invalid['statusCode'])

    def test_assigning_all_reviewers_from_staff_review_signals_once(self):
        application_id = self._staff_review()

        partial = self._call(
            'PUT',
            _REVIEWERS,
            {'compact': COMPACT, 'applicationId': application_id},
            {'firstReviewerSub': FIRST},
        )
        self.assertEqual(200, partial['statusCode'])
        self.assertEqual(FIRST, json.loads(partial['body'])['firstReviewerSub'])
        self.sfn.send_task_success.assert_not_called()

        complete = self._call(
            'PUT',
            _REVIEWERS,
            {'compact': COMPACT, 'applicationId': application_id},
            {'secondReviewerSub': SECOND, 'finalReviewerSub': FIRST},
        )
        self.assertEqual(200, complete['statusCode'], msg=complete['body'])
        self.assertEqual('first-review', json.loads(complete['body'])['status'])
        self.assertEqual(1, self.sfn.send_task_success.call_count)
        output = json.loads(self.sfn.send_task_success.call_args.kwargs['output'])
        self.assertEqual('REVIEWERS_ASSIGNED', output['action'])

        again = self._call(
            'PUT',
            _REVIEWERS,
            {'compact': COMPACT, 'applicationId': application_id},
            {'finalReviewerSub': SECOND},
        )
        self.assertEqual(200, again['statusCode'], msg=again['body'])
        self.assertEqual(1, self.sfn.send_task_success.call_count)

    def test_reviewer_assignment_rejects_the_same_person_and_a_jurisdiction_admin(self):
        application_id = self._staff_review()
        path = {'compact': COMPACT, 'applicationId': application_id}

        same_person = self._call(
            'PUT',
            _REVIEWERS,
            path,
            {'firstReviewerSub': FIRST, 'secondReviewerSub': FIRST},
        )
        jurisdiction = self._call('PUT', _REVIEWERS, path, {'firstReviewerSub': JURISDICTION_ONLY})

        self.assertEqual(400, same_person['statusCode'])
        self.assertIn(FIRST_AND_SECOND_REVIEWER_MUST_DIFFER, same_person['body'])
        self.assertEqual(400, jurisdiction['statusCode'])
        self.assertIn('Reviewer is not a compact admin', jurisdiction['body'])

    def test_section_review_follows_the_state_role(self):
        application_id = self._staff_review()
        path = {'compact': COMPACT, 'applicationId': application_id, 'section': 'personalInformation'}
        body = {'sectionStatus': 'approved', 'notesForApplicant': 'Looks complete'}

        too_early = self._call('PUT', _SECTION_REVIEW, path, body, sub=FIRST)
        self.assertEqual(400, too_early['statusCode'])

        self._assign(application_id, firstReviewerSub=FIRST, secondReviewerSub=SECOND, finalReviewerSub=FIRST)
        self._enter(StateName.FIRST_REVIEW, application_id)
        wrong_reviewer = self._call('PUT', _SECTION_REVIEW, path, body, sub=SECOND)
        saved = self._call('PUT', _SECTION_REVIEW, path, body, sub=FIRST)

        self.assertEqual(403, wrong_reviewer['statusCode'])
        self.assertEqual(200, saved['statusCode'], msg=saved['body'])
        section = json.loads(saved['body'])
        self.assertIn('calculatedSectionStatusForReviewComparison', section)
        self._assert_staff(section)

        self._enter(StateName.COMMITTEE_FROM_FIRST, application_id)
        committee_other = self._call('PUT', _SECTION_REVIEW, path, body, sub=SECOND)
        committee_sender = self._call('PUT', _SECTION_REVIEW, path, {'sectionStatus': 'rejected'}, sub=FIRST)

        self.assertEqual(403, committee_other['statusCode'])
        self.assertEqual(200, committee_sender['statusCode'], msg=committee_sender['body'])

    def test_transition_maps_illegal_actions_authorization_and_conflicts(self):
        application_id = self._create()
        path = {'compact': COMPACT, 'applicationId': application_id}

        illegal = self._call('POST', _TRANSITION, path, {'action': 'ADVANCE', 'requestId': 'req-illegal'})
        denied = self._call('POST', _TRANSITION, path, {'action': 'SUBMIT', 'requestId': 'req-submit'})

        self.assertEqual(400, illegal['statusCode'])
        self.assertEqual(403, denied['statusCode'])

        self._enter(StateName.STAFF_REVIEW, application_id)
        self.advance_on_callback = False
        pending = self._call(
            'POST',
            _TRANSITION,
            path,
            {'action': 'REVIEWERS_ASSIGNED', 'requestId': 'req-pending'},
        )
        conflict = self._call(
            'POST',
            _TRANSITION,
            path,
            {'action': 'REVIEWERS_ASSIGNED', 'requestId': 'req-conflict'},
        )

        self.assertEqual(202, pending['statusCode'])
        self.assertEqual('first-review', json.loads(pending['body'])['expectedStatus'])
        self.assertEqual(409, conflict['statusCode'])

    def test_admin_override_validates_the_target(self):
        application_id = self._create()
        path = {'compact': COMPACT, 'applicationId': application_id}

        rejected = self._call(
            'POST',
            _ADMIN_STATUS,
            path,
            {'targetState': 'FirstReview', 'reason': 'skip', 'requestId': 'req-bad-target'},
        )
        accepted = self._call(
            'POST',
            _ADMIN_STATUS,
            path,
            {'targetState': 'StaffReview', 'reason': 'move it', 'requestId': 'req-good-target'},
        )

        self.assertEqual(400, rejected['statusCode'])
        self.assertIn('Override target is not allowed', rejected['body'])
        self.assertEqual(200, accepted['statusCode'], msg=accepted['body'])
        body = json.loads(accepted['body'])
        self.assertEqual('staff-review', body['status'])
        self.assertEqual('StaffReview', body['stateName'])
        self._assert_staff(body)

    def test_reopen_delegates_to_the_reopen_service(self):
        application_id = self._create()

        response = self._call(
            'POST',
            _REOPEN,
            {'compact': COMPACT, 'applicationId': application_id},
            {'requestId': 'req-reopen', 'reason': 'start again'},
        )

        self.assertIn(response['statusCode'], (200, 202))
        body = json.loads(response['body'])
        self.assertEqual(application_id, body['id'])
        if response['statusCode'] == 202:
            self.assertEqual('staff-review', body['expectedStatus'])
            self.assertTrue(body['pending'])
        else:
            self.assertEqual('staff-review', body['status'])
        self.sfn.start_execution.assert_called()
        started = json.loads(self.sfn.start_execution.call_args.kwargs['input'])
        self.assertEqual('StaffReview', started['startAt'])
        self.assertEqual(application_id, started['applicationId'])

    def _call(self, method, resource, path, body=None, *, sub=ADMIN, scope='psypact/admin', query=None):
        return staff_applications.staff_applications(
            _event(method, resource, path, body, sub=sub, scope=scope, query=query),
            self.mock_context,
        )

    def _assert_staff(self, body: dict) -> None:
        encoded = json.dumps(body)
        for field_name in _HIDDEN:
            self.assertNotIn(field_name, encoded)

    def _create(self) -> str:
        application_id = str(uuid4())
        self.application_id = application_id
        self.config.application_client.create_application(
            COMPACT,
            application_id,
            execution_arn=self.workflow.execution_arn(COMPACT, application_id, 1),
            schedule_name=f'{application_id}-g1',
            workflow_expires_at='2027-11-06T00:00:00+00:00',
            provider_id=PROVIDER_ID,
            types=['apit'],
            is_renewal=False,
            created='2026-11-06T00:00:00+00:00',
        )
        self._enter(StateName.STARTED, application_id)
        return application_id

    def _staff_review(self) -> str:
        application_id = self._create()
        self._enter(StateName.STAFF_REVIEW, application_id)
        return application_id

    def _assign(self, application_id: str, **reviewers) -> None:
        application = self.config.application_client.get_application(COMPACT, application_id)
        self.config.application_client.assign_reviewers(
            COMPACT,
            application_id,
            reviewers,
            expected_version=int(application['version']),
        )

    def _create_tables(self) -> None:
        boto3.client('dynamodb').create_table(
            TableName=os.environ['APPLICATION_TABLE_NAME'],
            BillingMode='PAY_PER_REQUEST',
            AttributeDefinitions=[
                {'AttributeName': 'pk', 'AttributeType': 'S'},
                {'AttributeName': 'sk', 'AttributeType': 'S'},
                {'AttributeName': 'statusGSIPK', 'AttributeType': 'S'},
                {'AttributeName': 'statusGSISK', 'AttributeType': 'S'},
                {'AttributeName': 'actorGSIPK', 'AttributeType': 'S'},
                {'AttributeName': 'actorGSISK', 'AttributeType': 'S'},
            ],
            KeySchema=[
                {'AttributeName': 'pk', 'KeyType': 'HASH'},
                {'AttributeName': 'sk', 'KeyType': 'RANGE'},
            ],
            GlobalSecondaryIndexes=[
                _gsi('statusGSI', 'statusGSIPK', 'statusGSISK'),
                _gsi('actorGSI', 'actorGSIPK', 'actorGSISK'),
            ],
        )
        boto3.client('dynamodb').create_table(
            TableName=USERS_TABLE,
            BillingMode='PAY_PER_REQUEST',
            AttributeDefinitions=[
                {'AttributeName': 'pk', 'AttributeType': 'S'},
                {'AttributeName': 'sk', 'AttributeType': 'S'},
            ],
            KeySchema=[
                {'AttributeName': 'pk', 'KeyType': 'HASH'},
                {'AttributeName': 'sk', 'KeyType': 'RANGE'},
            ],
        )

    def _put_user(self, user_id: str, given_name: str, family_name: str, *, compact_admin: bool) -> None:
        permissions = {'jurisdictions': {}}
        if compact_admin:
            permissions['actions'] = {'admin'}
        else:
            permissions['jurisdictions'] = {'oh': {'admin'}}
        boto3.resource('dynamodb').Table(USERS_TABLE).put_item(
            Item={
                'pk': f'USER#{user_id}',
                'sk': f'COMPACT#{COMPACT}',
                'type': 'user',
                'dateOfUpdate': '2026-11-06T00:00:00+00:00',
                'userId': user_id,
                'compact': COMPACT,
                'status': 'active',
                'famGiv': f'{family_name}#{given_name}',
                'attributes': {
                    'email': f'{given_name.lower()}@example.com',
                    'givenName': given_name,
                    'familyName': family_name,
                },
                'permissions': permissions,
            }
        )

    def _on_start(self, **kwargs):
        body = json.loads(kwargs['input'])
        generation = int(body['generation'])
        self._enter(StateName(body['startAt']), body['applicationId'], generation)
        return {
            'executionArn': self.workflow.execution_arn(body['compact'], body['applicationId'], generation),
        }

    def _on_success(self, **kwargs):
        if self.advance_on_callback:
            output = json.loads(kwargs['output'])
            if output['action'] == 'ADMIN_OVERRIDE':
                state_name = StateName(output['targetState'])
            elif output['action'] == 'REVIEWERS_ASSIGNED':
                state_name = StateName.FIRST_REVIEW
            else:
                state_name = StateName.STAFF_REVIEW
            self._enter(state_name, self.application_id)
        return {}

    def _enter(self, state_name: StateName, application_id: str, generation: int = 1) -> None:
        self.entered += 1
        self.config.application_client.enter_state(
            COMPACT,
            application_id,
            execution_arn=self.workflow.execution_arn(COMPACT, application_id, generation),
            state_name=state_name,
            entered_time=f'2026-11-06T00:01:{self.entered:02d}+00:00',
            task_token=f'token-{self.entered}',
        )


def _gsi(name: str, partition: str, sort: str) -> dict:
    return {
        'IndexName': name,
        'KeySchema': [
            {'AttributeName': partition, 'KeyType': 'HASH'},
            {'AttributeName': sort, 'KeyType': 'RANGE'},
        ],
        'Projection': {'ProjectionType': 'ALL'},
    }
