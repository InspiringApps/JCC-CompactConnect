import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from cc_common.applicants.application_reopen_service import ApplicationReopenService
from cc_common.applicants.application_state import Caller, SectionName, StateName
from cc_common.applicants.application_transition_service import ApplicationTransitionService
from cc_common.applicants.application_workflow_client import ApplicationWorkflowClient, WorkflowStartAmbiguous
from cc_common.config import logger, metrics
from cc_common.psypact_config import PsypactConfig
from common_lambdas.exceptions import CCAccessDeniedException, CCConflictException
from moto import mock_aws

_APPLICANTS = Path(__file__).resolve().parents[3] / 'applicants-lambdas'
if _APPLICANTS.is_dir() and str(_APPLICANTS) not in sys.path:
    sys.path.insert(0, str(_APPLICANTS))

from handlers.execution_status_reconciler import execution_status_reconciler  # noqa: E402

from tests import TstLambdas  # noqa: E402

COMPACT = 'psypact'
APPLICATION_ID = 'app-1'
PROVIDER_ID = 'provider-1'
EXPIRES = '2027-11-05T00:00:00+00:00'
CREATED = '2026-11-05T00:00:00+00:00'
CALLBACK = 'callback-value'
ADMIN = Caller(sub='admin-sub', scopes={'psypact/admin'})
STAFF = Caller(sub='staff-sub', scopes={'oh/psypact.admin'})
FIRST = 'reviewer-first'
SECOND = 'reviewer-second'


def _missing_execution() -> ClientError:
    return ClientError(
        {'Error': {'Code': 'ExecutionDoesNotExist', 'Message': 'missing'}},
        'DescribeExecution',
    )


def _stale_token() -> ClientError:
    return ClientError(
        {'Error': {'Code': 'InvalidToken', 'Message': 'expired'}, 'ResponseMetadata': {'HTTPStatusCode': 400}},
        'SendTaskSuccess',
    )


@mock_aws
class TestApplicationReopenService(TstLambdas):
    def setUp(self):  # noqa: N801 invalid-name
        super().setUp()
        self._entered_count = 0
        self._application_table = boto3.resource('dynamodb').create_table(
            TableName=os.environ['APPLICATION_TABLE_NAME'],
            BillingMode='PAY_PER_REQUEST',
            AttributeDefinitions=[
                {'AttributeName': 'pk', 'AttributeType': 'S'},
                {'AttributeName': 'sk', 'AttributeType': 'S'},
                {'AttributeName': 'statusGSIPK', 'AttributeType': 'S'},
                {'AttributeName': 'statusGSISK', 'AttributeType': 'S'},
                {'AttributeName': 'actorGSIPK', 'AttributeType': 'S'},
                {'AttributeName': 'actorGSISK', 'AttributeType': 'S'},
                {'AttributeName': 'applicantGSIPK', 'AttributeType': 'S'},
                {'AttributeName': 'applicantGSISK', 'AttributeType': 'S'},
            ],
            KeySchema=[
                {'AttributeName': 'pk', 'KeyType': 'HASH'},
                {'AttributeName': 'sk', 'KeyType': 'RANGE'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': os.environ['APPLICATION_STATUS_GSI_NAME'],
                    'KeySchema': [
                        {'AttributeName': 'statusGSIPK', 'KeyType': 'HASH'},
                        {'AttributeName': 'statusGSISK', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
                {
                    'IndexName': os.environ['APPLICATION_ACTOR_GSI_NAME'],
                    'KeySchema': [
                        {'AttributeName': 'actorGSIPK', 'KeyType': 'HASH'},
                        {'AttributeName': 'actorGSISK', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
                {
                    'IndexName': os.environ['APPLICATION_APPLICANT_GSI_NAME'],
                    'KeySchema': [
                        {'AttributeName': 'applicantGSIPK', 'KeyType': 'HASH'},
                        {'AttributeName': 'applicantGSISK', 'KeyType': 'RANGE'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                },
            ],
        )
        self._application_table.meta.client.get_waiter('table_exists').wait(TableName=self._application_table.name)
        import common_lambdas.config as config_module

        self.psypact_config = PsypactConfig()
        config_module.config = self.psypact_config
        self.client = self.psypact_config.application_client
        self.sfn = MagicMockSfn()
        self.workflow = ApplicationWorkflowClient(os.environ['APPLICATION_STATE_MACHINE_ARN'], self.sfn)
        self.reasons_at_schedule = []
        self.service = ApplicationReopenService(
            self.psypact_config,
            workflow_client=self.workflow,
            transition_service=ApplicationTransitionService(
                self.psypact_config,
                workflow_client=self.workflow,
                sleeper=lambda _seconds: None,
                poll_timeout_seconds=0,
                backoff_seconds=0,
            ),
            schedule_creator=self._record_schedule,
            sleeper=lambda _seconds: None,
            poll_timeout_seconds=0,
            backoff_seconds=0,
        )
        metrics.metric_set.clear()
        self._schedule_delete = patch(
            'cc_common.applicants.application_schedule_client.ApplicationScheduleClient',
        ).start()
        self.addCleanup(patch.stopall)

    def test_reopen_from_each_terminal_status_starts_staff_review(self):
        for state_name in (StateName.APPROVED, StateName.REJECTED, StateName.DEACTIVATED):
            with self.subTest(state_name=state_name.value):
                self._reset()
                self._create()
                self._enter(state_name, terminal=True)
                self._preserve_review_history()
                self.sfn.describe_execution.return_value = {'status': 'SUCCEEDED'}
                self._succeeding_start()

                result = self.service.reopen(COMPACT, APPLICATION_ID, ADMIN, f'reopen-{state_name.value}', 'again')

                stored = self.client.get_application(COMPACT, APPLICATION_ID)
                self.assertFalse(result.pending)
                self.assertTrue(result.accepted)
                self.assertEqual(StateName.STAFF_REVIEW.value, stored['stateName'])
                self.assertEqual('staff-review', stored['status'])
                self.assertEqual(2, int(stored['generation']))
                self.assertNotIn('reopenLock', stored)
                self.assertEqual(FIRST, stored['firstReviewerSub'])
                self.assertEqual(SECOND, stored['secondReviewerSub'])
                self.assertEqual('assign-1', stored['reviews'][0]['assignmentId'])
                self.assertEqual('kept', self._section_data()['school'])
                self.assertEqual(6, self._section_count())
                self.sfn.send_task_success.assert_not_called()
                self.sfn.stop_execution.assert_not_called()
                started = json.loads(self.sfn.start_execution.call_args.kwargs['input'])
                self.assertEqual(StateName.STAFF_REVIEW.value, started['startAt'])
                self.assertEqual(2, started['generation'])

    def test_running_execution_is_deactivated_before_the_new_generation(self):
        self._create()
        self._enter(StateName.STAFF_REVIEW)
        self._running_until_deactivated()
        self._succeeding_start()

        result = self.service.reopen(COMPACT, APPLICATION_ID, ADMIN, 'reopen-running', 'again')

        self.assertFalse(result.pending)
        output = json.loads(self.sfn.send_task_success.call_args.kwargs['output'])
        self.assertEqual('ADMIN_DEACTIVATE', output['action'])
        self.assertEqual('reopen-running', output['requestId'])
        self.sfn.stop_execution.assert_not_called()
        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual(StateName.STAFF_REVIEW.value, stored['stateName'])
        self.assertEqual(2, int(stored['generation']))
        self.assertNotIn('ApplicationReopenForcedStop', metrics.metric_set)

    def test_expired_token_forces_a_stop_and_alarms(self):
        self._create()
        self._enter(StateName.STARTED)
        self.sfn.describe_execution.return_value = {'status': 'RUNNING'}
        self.sfn.send_task_success.side_effect = _stale_token()
        self._succeeding_start()

        with self.assertLogs(logger.name, level='ERROR') as captured:
            result = self.service.reopen(COMPACT, APPLICATION_ID, ADMIN, 'reopen-stuck', 'again')

        self.assertFalse(result.pending)
        self.sfn.stop_execution.assert_called_once()
        self.assertEqual('REOPEN_FORCED_STOP', self.sfn.stop_execution.call_args.kwargs['cause'])
        self.assertEqual(['REOPEN_FORCED_STOP'], self.reasons_at_schedule)
        self.assertIn('ApplicationReopenForcedStop', metrics.metric_set)
        self.assertIn(APPLICATION_ID, '\n'.join(captured.output))
        self.assertNotIn('again', '\n'.join(captured.output))
        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual(2, int(stored['generation']))
        self.assertEqual(StateName.STAFF_REVIEW.value, stored['stateName'])

    def test_broken_executions_are_reconciled_without_a_callback(self):
        for status, reason in (
            ('FAILED', 'EXECUTION_FAILED'),
            ('TIMED_OUT', 'EXECUTION_TIMED_OUT'),
            ('ABORTED', 'EXECUTION_ABORTED'),
        ):
            with self.subTest(status=status):
                self._reset()
                self._create()
                self._enter(StateName.STARTED)
                self.sfn.describe_execution.return_value = {'status': status}
                self._succeeding_start()

                result = self.service.reopen(COMPACT, APPLICATION_ID, ADMIN, f'reopen-{status}', 'again')

                self.assertFalse(result.pending)
                self.assertEqual([reason], self.reasons_at_schedule)
                self.sfn.send_task_success.assert_not_called()
                self.sfn.stop_execution.assert_not_called()
                stored = self.client.get_application(COMPACT, APPLICATION_ID)
                self.assertEqual(2, int(stored['generation']))
                self.assertEqual(StateName.STAFF_REVIEW.value, stored['stateName'])

    def test_same_request_resumes_after_the_lock_the_commit_and_the_start(self):
        self._create()
        self._enter(StateName.APPROVED, terminal=True)
        self.sfn.describe_execution.side_effect = self._describe_old_succeeded
        self.client.acquire_reopen_lock(COMPACT, APPLICATION_ID, 'reopen-1')
        self.sfn.start_execution.side_effect = self._fail_then_start

        with self.assertRaises(WorkflowStartAmbiguous):
            self.service.reopen(COMPACT, APPLICATION_ID, ADMIN, 'reopen-1', 'again')
        after_commit = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual(2, int(after_commit['generation']))
        self.assertIn('reopenLock', after_commit)

        result = self.service.reopen(COMPACT, APPLICATION_ID, ADMIN, 'reopen-1', 'again')
        replay = self.service.reopen(COMPACT, APPLICATION_ID, ADMIN, 'reopen-1', 'again')

        self.assertFalse(result.pending)
        self.assertEqual(result.as_dict(), replay.as_dict())
        self.assertEqual(2, int(self.client.get_application(COMPACT, APPLICATION_ID)['generation']))
        self.assertEqual(3, self.sfn.start_execution.call_count)
        first_input = self.sfn.start_execution.call_args_list[0].kwargs['input']
        self.assertEqual(first_input, self.sfn.start_execution.call_args_list[1].kwargs['input'])
        self.assertEqual(first_input, self.sfn.start_execution.call_args_list[2].kwargs['input'])

    def test_a_different_request_conflicts_while_the_lock_is_held(self):
        self._create()
        self._enter(StateName.APPROVED, terminal=True)
        self.client.acquire_reopen_lock(COMPACT, APPLICATION_ID, 'reopen-1')

        with self.assertRaises(CCConflictException):
            self.service.reopen(COMPACT, APPLICATION_ID, ADMIN, 'reopen-2', 'other')

        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual(1, int(stored['generation']))
        self.assertEqual('reopen-1', stored['reopenLock']['requestId'])

    def test_release_before_commit_drops_the_lock_and_release_after_commit_does_not(self):
        self._create()
        self._enter(StateName.APPROVED, terminal=True)
        locked = self.client.acquire_reopen_lock(COMPACT, APPLICATION_ID, 'reopen-1')
        self.assertTrue(self.client.release_reopen_lock_on_failure(COMPACT, APPLICATION_ID, 'reopen-1'))
        self.assertNotIn('reopenLock', self.client.get_application(COMPACT, APPLICATION_ID))

        locked = self.client.acquire_reopen_lock(COMPACT, APPLICATION_ID, 'reopen-1')
        self.client.commit_reopen_generation(
            COMPACT,
            APPLICATION_ID,
            'reopen-1',
            self.workflow.execution_arn(COMPACT, APPLICATION_ID, 2),
            'app-1-g2',
            locked['reopenLock']['workflowExpiresAt'],
        )
        self.assertFalse(self.client.release_reopen_lock_on_failure(COMPACT, APPLICATION_ID, 'reopen-1'))
        self.assertEqual('reopen-1', self.client.get_application(COMPACT, APPLICATION_ID)['reopenLock']['requestId'])

    def test_a_non_admin_cannot_reopen(self):
        self._create()
        self._enter(StateName.APPROVED, terminal=True)

        with self.assertRaises(CCAccessDeniedException):
            self.service.reopen(COMPACT, APPLICATION_ID, STAFF, 'reopen-1', 'again')

        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertNotIn('reopenLock', stored)
        self.assertEqual(1, int(stored['generation']))

    def test_a_late_reconciler_event_cannot_overwrite_the_new_generation(self):
        self._create()
        self._enter(StateName.APPROVED, terminal=True)
        self.sfn.describe_execution.return_value = {'status': 'SUCCEEDED'}
        self._succeeding_start()
        self.service.reopen(COMPACT, APPLICATION_ID, ADMIN, 'reopen-1', 'again')
        metrics.metric_set.clear()

        result = execution_status_reconciler(
            {
                'detail': {
                    'executionArn': self.workflow.execution_arn(COMPACT, APPLICATION_ID, 1),
                    'stateMachineArn': os.environ['APPLICATION_STATE_MACHINE_ARN'],
                    'name': 'app-1-g1',
                    'status': 'ABORTED',
                    'input': json.dumps({'compact': COMPACT, 'applicationId': APPLICATION_ID}),
                },
            },
            self.mock_context,
        )

        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual('stale', result['outcome'])
        self.assertEqual(2, int(stored['generation']))
        self.assertEqual(StateName.STAFF_REVIEW.value, stored['stateName'])
        self.assertEqual('staff-review', stored['status'])
        self.assertNotIn('ApplicationExecutionBroken', metrics.metric_set)

    def _record_schedule(self, **_kwargs):
        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.reasons_at_schedule.append(stored.get('deactivationReason'))

    def _create(self):
        self.client.create_application(
            COMPACT,
            APPLICATION_ID,
            execution_arn=self.workflow.execution_arn(COMPACT, APPLICATION_ID, 1),
            schedule_name='app-1-g1',
            workflow_expires_at=EXPIRES,
            provider_id=PROVIDER_ID,
            types=['apit'],
            is_renewal=False,
            created=CREATED,
        )

    def _enter(self, state_name: StateName, *, terminal: bool = False, generation: int = 1) -> dict:
        self._entered_count += 1
        return self.client.enter_state(
            COMPACT,
            APPLICATION_ID,
            execution_arn=self.workflow.execution_arn(COMPACT, APPLICATION_ID, generation),
            state_name=state_name,
            entered_time=f'2026-11-05T00:01:{self._entered_count:02d}+00:00',
            task_token=None if terminal else CALLBACK,
            terminal=terminal,
        )

    def _preserve_review_history(self):
        self._application_table.update_item(
            Key=self._key('APPLICATION'),
            UpdateExpression='SET firstReviewerSub = :first, secondReviewerSub = :second, reviews = :reviews',
            ExpressionAttributeValues={
                ':first': FIRST,
                ':second': SECOND,
                ':reviews': [{'assignmentId': 'assign-1', 'reviewerType': 'first-reviewer'}],
            },
        )
        self._application_table.update_item(
            Key=self._key(self.client.section_sk(SectionName.EDUCATION)),
            UpdateExpression='SET #data = :data',
            ExpressionAttributeNames={'#data': 'data'},
            ExpressionAttributeValues={':data': {'school': 'kept'}},
        )

    def _running_until_deactivated(self):
        status = {'value': 'RUNNING'}

        def describe(**_kwargs):
            return {'status': status['value']}

        def send(**_kwargs):
            self._enter(StateName.DEACTIVATED, terminal=True)
            status['value'] = 'SUCCEEDED'
            return {}

        self.sfn.describe_execution.side_effect = describe
        self.sfn.send_task_success.side_effect = send

    def _succeeding_start(self):
        def start(**kwargs):
            body = json.loads(kwargs['input'])
            self._enter(StateName.STAFF_REVIEW, generation=int(body['generation']))
            return {'executionArn': kwargs['name']}

        self.sfn.start_execution.side_effect = start

    def _fail_then_start(self, **kwargs):
        if self.sfn.start_execution.call_count <= 2:
            raise BotoCoreError
        body = json.loads(kwargs['input'])
        self._enter(StateName.STAFF_REVIEW, generation=int(body['generation']))
        return {'executionArn': kwargs['name']}

    def _describe_old_succeeded(self, **kwargs):
        if str(kwargs.get('executionArn', '')).endswith(':app-1-g2'):
            raise _missing_execution()
        return {'status': 'SUCCEEDED'}

    def _section_data(self) -> dict:
        stored = self._application_table.get_item(Key=self._key(self.client.section_sk(SectionName.EDUCATION)))
        return stored['Item'].get('data') or {}

    def _section_count(self) -> int:
        response = self._items()
        return sum(1 for item in response if str(item['sk']).startswith('SECTION#'))

    def _reset(self):
        for item in self._items():
            self._application_table.delete_item(Key={'pk': item['pk'], 'sk': item['sk']})
        self.reasons_at_schedule.clear()
        self.sfn.reset_mock()
        metrics.metric_set.clear()

    def _items(self) -> list:
        response = self._application_table.query(
            KeyConditionExpression=Key('pk').eq(self.client.pk(COMPACT, APPLICATION_ID)),
        )
        return response['Items']

    def _key(self, sort_key: str) -> dict:
        return {'pk': self.client.pk(COMPACT, APPLICATION_ID), 'sk': sort_key}


class MagicMockSfn:
    """A small stand-in so each test can replace one Step Functions call without a full mock."""

    def __init__(self):
        from unittest.mock import MagicMock

        self.describe_execution = MagicMock()
        self.send_task_success = MagicMock()
        self.stop_execution = MagicMock()
        self.start_execution = MagicMock()

    def reset_mock(self):
        self.describe_execution.reset_mock()
        self.send_task_success.reset_mock()
        self.stop_execution.reset_mock()
        self.start_execution.reset_mock()
        self.describe_execution.side_effect = None
        self.send_task_success.side_effect = None
        self.stop_execution.side_effect = None
        self.start_execution.side_effect = None
