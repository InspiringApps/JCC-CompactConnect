import json
import os
from unittest.mock import MagicMock, patch

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from cc_common.applicants.application_schedule_client import ApplicationScheduleClient
from cc_common.applicants.application_state import Caller, StateName
from cc_common.applicants.application_transition_service import (
    ApplicationTransitionService,
    TransitionResult,
    _default_schedule_creator,
)
from cc_common.config import logger, metrics
from cc_common.psypact_config import PsypactConfig
from handlers.enter_state import enter_state
from handlers.expiry_deactivation import expiry_deactivation
from moto import mock_aws

from tests import TstLambdas

COMPACT = 'psypact'
APPLICATION_ID = 'app-1'
PROVIDER_ID = 'provider-1'
EXECUTION_ARN = 'arn:aws:states:us-east-1:000000000000:execution:ApplicationWorkflow:app-1-g1'
SCHEDULE_NAME = 'app-1-g1'
ENTERED_TIME = '2026-11-05T00:00:01+00:00'
TERMINAL_TIME = '2026-11-05T00:00:02+00:00'
CALLBACK_VALUE = 'callback-secret-value'
_TERMINAL_STATUSES = (StateName.APPROVED, StateName.REJECTED, StateName.DEACTIVATED)


@mock_aws
class TestExpiryDeactivation(TstLambdas):
    def setUp(self):  # noqa: N801 invalid-name
        super().setUp()
        os.environ['APPLICATION_STATE_MACHINE_ARN'] = (
            'arn:aws:states:us-east-1:000000000000:stateMachine:ApplicationWorkflow'
        )
        self._create_table()
        import common_lambdas.config as config_module

        self.psypact_config = PsypactConfig()
        config_module.config = self.psypact_config
        self.client = self.psypact_config.application_client
        metrics.metric_set.clear()

    def test_create_expiry_schedule_is_deterministic_and_conflict_is_success(self):
        scheduler = MagicMock()
        client = ApplicationScheduleClient(scheduler)
        name = client.create_expiry_schedule(
            COMPACT,
            APPLICATION_ID,
            1,
            '2027-11-04T23:00:00+00:00',
            group_name='application-workflow',
            target_arn='arn:aws:lambda:us-east-1:000000000000:function:expiry',
            role_arn='arn:aws:iam::000000000000:role/scheduler',
        )

        self.assertEqual(SCHEDULE_NAME, name)
        kwargs = scheduler.create_schedule.call_args.kwargs
        self.assertEqual('at(2027-11-04T23:00:00)', kwargs['ScheduleExpression'])
        self.assertEqual('UTC', kwargs['ScheduleExpressionTimezone'])
        self.assertEqual('DELETE', kwargs['ActionAfterCompletion'])
        self.assertEqual('application-workflow', kwargs['GroupName'])
        self.assertEqual(
            {
                'applicationId': APPLICATION_ID,
                'compact': COMPACT,
                'generation': 1,
                'scheduleName': SCHEDULE_NAME,
            },
            json.loads(kwargs['Target']['Input']),
        )

        scheduler.create_schedule.side_effect = ClientError(
            {'Error': {'Code': 'ConflictException', 'Message': 'exists'}},
            'CreateSchedule',
        )
        self.assertEqual(
            SCHEDULE_NAME,
            client.create_expiry_schedule(
                COMPACT,
                APPLICATION_ID,
                1,
                '2027-11-04T23:00:00+00:00',
                group_name='application-workflow',
                target_arn='arn:aws:lambda:us-east-1:000000000000:function:expiry',
                role_arn='arn:aws:iam::000000000000:role/scheduler',
            ),
        )

        scheduler.create_schedule.side_effect = ClientError(
            {'Error': {'Code': 'AccessDeniedException', 'Message': 'no'}},
            'CreateSchedule',
        )
        with self.assertRaises(ClientError):
            client.create_expiry_schedule(
                COMPACT,
                APPLICATION_ID,
                1,
                '2027-11-04T23:00:00+00:00',
                group_name='application-workflow',
                target_arn='arn:aws:lambda:us-east-1:000000000000:function:expiry',
                role_arn='arn:aws:iam::000000000000:role/scheduler',
            )

    def test_default_schedule_creator_uses_the_configured_expiry_target(self):
        with patch.dict(
            os.environ,
            {
                'APPLICATION_SCHEDULE_GROUP_NAME': 'application-workflow',
                'APPLICATION_EXPIRY_FUNCTION_ARN': 'arn:aws:lambda:us-east-1:000000000000:function:expiry',
                'APPLICATION_SCHEDULER_ROLE_ARN': 'arn:aws:iam::000000000000:role/scheduler',
            },
        ):
            with patch('cc_common.applicants.application_schedule_client.ApplicationScheduleClient') as schedule_client:
                _default_schedule_creator(PsypactConfig())(
                    compact=COMPACT,
                    application_id=APPLICATION_ID,
                    generation=1,
                    schedule_name=SCHEDULE_NAME,
                    workflow_expires_at='2027-11-04T23:00:00+00:00',
                    execution_arn=EXECUTION_ARN,
                )

        schedule_client.return_value.create_expiry_schedule.assert_called_once_with(
            COMPACT,
            APPLICATION_ID,
            1,
            '2027-11-04T23:00:00+00:00',
            group_name='application-workflow',
            target_arn='arn:aws:lambda:us-east-1:000000000000:function:expiry',
            role_arn='arn:aws:iam::000000000000:role/scheduler',
        )

    def test_terminal_status_is_a_silent_no_op(self):
        for state_name in _TERMINAL_STATUSES:
            with self.subTest(state_name=state_name.value):
                self._reset_application()
                self._enter_started()
                enter_state(self._terminal_event(state_name), self.mock_context)
                self._assert_no_op(self._event())

    def test_stale_generation_mismatched_schedule_and_reopen_lock_are_no_ops(self):
        self._enter_started()
        stale = self._event()
        stale['generation'] = 2
        stale['scheduleName'] = 'app-1-g2'
        self._assert_no_op(stale)

        mismatched = self._event()
        mismatched['scheduleName'] = 'other-schedule'
        self._assert_no_op(mismatched)

        self._set_reopen_lock()
        self._assert_no_op(self._event())

    def test_active_application_is_deactivated_by_the_system_caller(self):
        self._enter_started()
        accepted = TransitionResult(
            application_id=APPLICATION_ID,
            request_id=f'expiry-{APPLICATION_ID}-g1',
            pending=False,
            accepted=True,
        )
        with patch.object(ApplicationTransitionService, 'admin_deactivate', return_value=accepted) as deactivate:
            result = expiry_deactivation(self._event(), self.mock_context)

        self.assertTrue(result['deactivated'])
        compact, application_id, caller, request_id = deactivate.call_args.args
        self.assertEqual(COMPACT, compact)
        self.assertEqual(APPLICATION_ID, application_id)
        self.assertEqual(f'expiry-{APPLICATION_ID}-g1', request_id)
        self.assertIsInstance(caller, Caller)
        self.assertEqual({f'{COMPACT}/admin'}, caller.scopes)
        self.assertNotIn('ApplicationExpiryDeactivationFailed', metrics.metric_set)

    def test_a_failed_deactivation_is_logged_and_counted(self):
        self._enter_started()
        with patch.object(ApplicationTransitionService, 'admin_deactivate', side_effect=RuntimeError('down')):
            with self.assertLogs(logger.name, level='ERROR') as captured:
                with self.assertRaises(RuntimeError):
                    expiry_deactivation(self._event(), self.mock_context)

        self.assertIn(APPLICATION_ID, '\n'.join(captured.output))
        self.assertIn('ApplicationExpiryDeactivationFailed', metrics.metric_set)
        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual('started', stored['status'])

    def _assert_no_op(self, event: dict):
        before = self.client.get_application(COMPACT, APPLICATION_ID)
        metrics.metric_set.clear()
        with patch.object(ApplicationTransitionService, 'admin_deactivate') as deactivate:
            with patch.object(logger, 'error') as error_log:
                result = expiry_deactivation(event, self.mock_context)
        deactivate.assert_not_called()
        error_log.assert_not_called()
        self.assertFalse(result['deactivated'])
        self.assertNotIn('ApplicationExpiryDeactivationFailed', metrics.metric_set)
        after = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual(before, after)

    def _enter_started(self):
        self.client.create_application(
            COMPACT,
            APPLICATION_ID,
            execution_arn=EXECUTION_ARN,
            schedule_name=SCHEDULE_NAME,
            workflow_expires_at='2027-11-04T23:00:00+00:00',
            provider_id=PROVIDER_ID,
            types=['apit'],
            is_renewal=False,
            created='2026-11-05T00:00:00+00:00',
        )
        enter_state(self._started_event(), self.mock_context)

    def _reset_application(self):
        response = self._application_table.query(
            KeyConditionExpression=Key('pk').eq(f'{COMPACT}#APPLICATION#{APPLICATION_ID}'),
        )
        for item in response['Items']:
            self._application_table.delete_item(Key={'pk': item['pk'], 'sk': item['sk']})

    def _set_reopen_lock(self):
        self._application_table.update_item(
            Key={'pk': f'{COMPACT}#APPLICATION#{APPLICATION_ID}', 'sk': 'APPLICATION'},
            UpdateExpression='SET reopenLock = :lock',
            ExpressionAttributeValues={
                ':lock': {'requestId': 'reopen-1', 'oldGeneration': 1, 'oldExecutionArn': EXECUTION_ARN},
            },
        )

    def _event(self) -> dict:
        return {
            'compact': COMPACT,
            'applicationId': APPLICATION_ID,
            'generation': 1,
            'scheduleName': SCHEDULE_NAME,
        }

    def _started_event(self) -> dict:
        return {
            'mode': 'ENTER',
            'compact': COMPACT,
            'applicationId': APPLICATION_ID,
            'generation': 1,
            'stateName': StateName.STARTED.value,
            'executionArn': EXECUTION_ARN,
            'enteredTime': ENTERED_TIME,
            'taskToken': CALLBACK_VALUE,
        }

    def _terminal_event(self, state_name: StateName) -> dict:
        event = self._started_event()
        event.update({'mode': 'TERMINAL', 'stateName': state_name.value, 'enteredTime': TERMINAL_TIME})
        return event

    def _create_table(self):
        import boto3

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
