import json
import os
from unittest.mock import patch

from boto3.dynamodb.conditions import Key
from cc_common.applicants.application_state import StateName
from cc_common.config import logger, metrics
from cc_common.psypact_config import PsypactConfig
from handlers.enter_state import enter_state
from handlers.execution_status_reconciler import execution_status_reconciler
from moto import mock_aws

from tests import TstLambdas

COMPACT = 'psypact'
APPLICATION_ID = 'app-1'
PROVIDER_ID = 'provider-1'
EXECUTION_ARN = 'arn:aws:states:us-east-1:000000000000:execution:ApplicationWorkflow:app-1-g1'
NEXT_EXECUTION_ARN = 'arn:aws:states:us-east-1:000000000000:execution:ApplicationWorkflow:app-1-g2'
SCHEDULE_NAME = 'app-1-g1'
ENTERED_TIME = '2026-11-05T00:00:01+00:00'
CALLBACK_VALUE = 'callback-secret-value'
_REASONS = {
    'FAILED': 'EXECUTION_FAILED',
    'TIMED_OUT': 'EXECUTION_TIMED_OUT',
    'ABORTED': 'EXECUTION_ABORTED',
}


@mock_aws
class TestExecutionStatusReconciler(TstLambdas):
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

    def test_each_failing_status_records_internal_error(self):
        for status, reason in _REASONS.items():
            with self.subTest(status=status):
                self._reset_items()
                self._enter_started()
                self._set_pending()
                metrics.metric_set.clear()
                with patch('handlers.execution_status_reconciler.ApplicationScheduleClient') as schedule:
                    with self.assertLogs(logger.name, level='ERROR') as captured:
                        result = execution_status_reconciler(self._event(status), self.mock_context)

                self.assertEqual('applied', result['outcome'])
                stored = self.client.get_application(COMPACT, APPLICATION_ID)
                self.assertEqual('internal-error', stored['status'])
                self.assertEqual(StateName.INTERNAL_ERROR.value, stored['stateName'])
                self.assertEqual(reason, stored['deactivationReason'])
                self.assertEqual('States.Runtime boom', stored['lastExecutionError'])
                self.assertIn('completed', stored)
                self.assertNotIn('taskToken', stored)
                self.assertNotIn('pendingAction', stored)
                self.assertNotIn('actorGSIPK', stored)
                self.assertEqual(1, self._internal_error_audits())
                self.assertIn('ApplicationExecutionBroken', metrics.metric_set)
                self.assertNotIn('ApplicationReopenForcedStop', metrics.metric_set)
                self.assertIn(APPLICATION_ID, '\n'.join(captured.output))
                self.assertIn(EXECUTION_ARN, '\n'.join(captured.output))
                schedule.return_value.delete_schedule.assert_called_once()

    def test_stale_generation_is_not_written_or_alarmed(self):
        self._enter_started()
        before = self.client.get_application(COMPACT, APPLICATION_ID)
        event = self._event('FAILED', name='app-1-g2', execution_arn=NEXT_EXECUTION_ARN)
        with patch('handlers.execution_status_reconciler.ApplicationScheduleClient') as schedule:
            result = execution_status_reconciler(event, self.mock_context)

        self.assertEqual('stale', result['outcome'])
        self.assertEqual(before, self.client.get_application(COMPACT, APPLICATION_ID))
        self.assertNotIn('ApplicationExecutionBroken', metrics.metric_set)
        schedule.return_value.delete_schedule.assert_not_called()

    def test_succeeded_and_running_events_are_ignored(self):
        self._enter_started()
        before = self.client.get_application(COMPACT, APPLICATION_ID)
        for status in ('SUCCEEDED', 'RUNNING'):
            with self.subTest(status=status):
                result = execution_status_reconciler(self._event(status), self.mock_context)
                self.assertFalse(result['acted'])
                self.assertEqual(before, self.client.get_application(COMPACT, APPLICATION_ID))
                self.assertNotIn('ApplicationExecutionBroken', metrics.metric_set)

    def test_abort_during_reopen_does_not_overwrite_the_new_generation(self):
        self._enter_started()
        self._application_table.update_item(
            Key={'pk': f'{COMPACT}#APPLICATION#{APPLICATION_ID}', 'sk': 'APPLICATION'},
            UpdateExpression='SET generation = :generation, executionArn = :arn, reopenLock = :lock',
            ExpressionAttributeValues={
                ':generation': 2,
                ':arn': NEXT_EXECUTION_ARN,
                ':lock': {'requestId': 'reopen-1', 'oldGeneration': 1, 'oldExecutionArn': EXECUTION_ARN},
            },
        )
        with patch('handlers.execution_status_reconciler.ApplicationScheduleClient') as schedule:
            result = execution_status_reconciler(self._event('ABORTED'), self.mock_context)

        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual('reopen-observed', result['outcome'])
        self.assertEqual(2, int(stored['generation']))
        self.assertEqual(NEXT_EXECUTION_ARN, stored['executionArn'])
        self.assertEqual('started', stored['status'])
        self.assertIn('ApplicationReopenForcedStop', metrics.metric_set)
        self.assertNotIn('ApplicationExecutionBroken', metrics.metric_set)
        schedule.return_value.delete_schedule.assert_not_called()

    def test_replay_of_an_internal_error_does_not_write_again(self):
        self._enter_started()
        with patch('handlers.execution_status_reconciler.ApplicationScheduleClient'):
            execution_status_reconciler(self._event('FAILED'), self.mock_context)
        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        metrics.metric_set.clear()
        with patch('handlers.execution_status_reconciler.ApplicationScheduleClient') as schedule:
            result = execution_status_reconciler(self._event('FAILED'), self.mock_context)

        replayed = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual('already', result['outcome'])
        self.assertEqual(stored['version'], replayed['version'])
        self.assertEqual(stored['dateOfUpdate'], replayed['dateOfUpdate'])
        self.assertEqual(1, self._internal_error_audits())
        self.assertNotIn('ApplicationExecutionBroken', metrics.metric_set)
        schedule.return_value.delete_schedule.assert_not_called()

    def _event(self, status: str, *, name: str = SCHEDULE_NAME, execution_arn: str = EXECUTION_ARN) -> dict:
        return {
            'detail-type': 'Step Functions Execution Status Change',
            'source': 'aws.states',
            'detail': {
                'executionArn': execution_arn,
                'stateMachineArn': os.environ['APPLICATION_STATE_MACHINE_ARN'],
                'name': name,
                'status': status,
                'input': json.dumps({'compact': COMPACT, 'applicationId': APPLICATION_ID}),
                'error': 'States.Runtime',
                'cause': 'boom',
            },
        }

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
        enter_state(
            {
                'compact': COMPACT,
                'applicationId': APPLICATION_ID,
                'generation': 1,
                'stateName': StateName.STARTED.value,
                'executionArn': EXECUTION_ARN,
                'enteredTime': ENTERED_TIME,
                'taskToken': CALLBACK_VALUE,
            },
            self.mock_context,
        )

    def _set_pending(self):
        self._application_table.update_item(
            Key={'pk': f'{COMPACT}#APPLICATION#{APPLICATION_ID}', 'sk': 'APPLICATION'},
            UpdateExpression='SET pendingAction = :pending',
            ExpressionAttributeValues={':pending': {'requestId': 'pending-1'}},
        )

    def _internal_error_audits(self) -> int:
        response = self._application_table.query(
            KeyConditionExpression=Key('pk').eq(f'{COMPACT}#APPLICATION#{APPLICATION_ID}')
            & Key('sk').begins_with('TRANSITION#'),
        )
        return sum(1 for item in response['Items'] if item.get('toState') == StateName.INTERNAL_ERROR.value)

    def _reset_items(self):
        response = self._application_table.query(
            KeyConditionExpression=Key('pk').eq(f'{COMPACT}#APPLICATION#{APPLICATION_ID}'),
        )
        for item in response['Items']:
            self._application_table.delete_item(Key={'pk': item['pk'], 'sk': item['sk']})

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
