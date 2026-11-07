import json
import logging
import os
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError
from cc_common.applicants.application_schedule_client import ApplicationScheduleClient
from cc_common.applicants.application_state import StateName
from cc_common.config import logger
from cc_common.psypact_config import PsypactConfig
from common_lambdas.exceptions import CCConflictException
from enter_state import enter_state
from handlers.enter_state import _task_token
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


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        parts = [record.getMessage()]
        for value in record.__dict__.values():
            if isinstance(value, str):
                parts.append(value)
        self.messages.append('\n'.join(parts))


@mock_aws
class TestEnterState(TstLambdas):
    def setUp(self):  # noqa: N801 invalid-name
        super().setUp()
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

    def test_wait_node_entry_writes_state_and_clears_pending(self):
        self._create()
        self._set_pending('before-entry')

        with self._captured_logs() as captured:
            result = enter_state(self._event(), self.mock_context)

        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual('started', stored['status'])
        self.assertEqual(StateName.STARTED.value, stored['stateName'])
        self.assertEqual(CALLBACK_VALUE, stored['taskToken'])
        self.assertEqual(f'{COMPACT}#STATUS#started', stored['statusGSIPK'])
        self.assertEqual(f'{COMPACT}#ACTOR#{PROVIDER_ID}', stored['actorGSIPK'])
        self.assertNotIn('pendingAction', stored)
        self.assertEqual(APPLICATION_ID, result['applicationId'])
        self.assertNotIn('taskToken', result)
        self._assert_token_absent(result, captured)

    def test_replay_is_a_no_op_and_keeps_a_later_pending_action(self):
        self._create()
        first = enter_state(self._event(), self.mock_context)
        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self._set_pending('later-request')

        second = enter_state(self._event(), self.mock_context)

        replayed = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual(stored['version'], replayed['version'])
        self.assertEqual(stored['dateOfUpdate'], replayed['dateOfUpdate'])
        self.assertEqual('later-request', replayed['pendingAction']['requestId'])
        self.assertEqual(first['stateName'], second['stateName'])
        self.assertNotIn(CALLBACK_VALUE, json.dumps(second))

    def test_wrong_generation_raises_without_writing(self):
        self._create()
        event = self._event()
        event['generation'] = 2

        with self.assertRaises(CCConflictException):
            enter_state(event, self.mock_context)

        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertNotIn('status', stored)
        self.assertNotIn('taskToken', stored)

    def test_terminal_entry_removes_token_and_deletes_schedule(self):
        self._create()
        enter_state(self._event(), self.mock_context)

        with patch('handlers.enter_state.ApplicationScheduleClient') as schedule_client:
            result = enter_state(self._terminal_event(), self.mock_context)

        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual(StateName.APPROVED.value, stored['stateName'])
        self.assertIn('completed', stored)
        self.assertNotIn('taskToken', stored)
        self.assertNotIn('taskTokenHash', stored)
        self.assertNotIn('actorGSIPK', stored)
        self.assertNotIn('deactivationReason', stored)
        schedule_client.return_value.delete_schedule.assert_called_once_with(
            SCHEDULE_NAME,
            application_id=APPLICATION_ID,
            group_name=os.environ['APPLICATION_SCHEDULE_GROUP_NAME'],
        )
        self.assertNotIn(CALLBACK_VALUE, json.dumps(result))

    def test_terminal_admin_deactivate_records_the_transition_action(self):
        self._create()
        enter_state(self._event(), self.mock_context)
        event = self._terminal_event(state_name=StateName.DEACTIVATED)
        event['transition'] = {'action': 'ADMIN_DEACTIVATE'}

        enter_state(event, self.mock_context)

        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual('ADMIN_DEACTIVATE', stored['deactivationReason'])

    def test_terminal_schedule_delete_failure_does_not_fail_the_handler(self):
        self._create()
        enter_state(self._event(), self.mock_context)

        with patch('handlers.enter_state.ApplicationScheduleClient') as schedule_client:
            schedule_client.return_value.delete_schedule.side_effect = RuntimeError('scheduler down')
            result = enter_state(
                self._terminal_event(state_name=StateName.DEACTIVATED, error='TIMEOUT'),
                self.mock_context,
            )

        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual('TIMEOUT', stored['deactivationReason'])
        self.assertIn('completed', stored)
        self.assertEqual(StateName.DEACTIVATED.value, result['stateName'])
        self.assertNotIn('taskToken', result)

    def test_delete_schedule_swallows_errors_and_logs_the_application_id(self):
        missing = ClientError(
            {'Error': {'Code': 'ResourceNotFoundException', 'Message': 'missing'}},
            'DeleteSchedule',
        )
        scheduler = MagicMock()
        scheduler.delete_schedule.side_effect = missing
        with self.assertLogs(logger.name, level='ERROR') as captured:
            ApplicationScheduleClient(scheduler).delete_schedule(SCHEDULE_NAME, application_id=APPLICATION_ID)
        self.assertIn(APPLICATION_ID, '\n'.join(captured.output))

        scheduler.delete_schedule.side_effect = RuntimeError('unavailable')
        with self.assertLogs(logger.name, level='ERROR') as captured:
            ApplicationScheduleClient(scheduler).delete_schedule(SCHEDULE_NAME, application_id=APPLICATION_ID)
        self.assertIn(APPLICATION_ID, '\n'.join(captured.output))

    def test_logs_redact_the_task_token(self):
        token = _task_token.set(CALLBACK_VALUE)
        try:
            with self._captured_logs() as captured:
                logger.info('callback %s', CALLBACK_VALUE, taskToken=CALLBACK_VALUE)
        finally:
            _task_token.reset(token)
        self._assert_token_absent({}, captured)

    def _create(self):
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

    def _event(self) -> dict:
        return {
            'mode': 'ENTER',
            'compact': COMPACT,
            'applicationId': APPLICATION_ID,
            'generation': 1,
            'stateName': StateName.STARTED.value,
            'executionArn': EXECUTION_ARN,
            'enteredTime': ENTERED_TIME,
            'taskToken': CALLBACK_VALUE,
            'error': None,
        }

    def _terminal_event(self, state_name: StateName = StateName.APPROVED, error=None) -> dict:
        event = self._event()
        event.update(
            {
                'mode': 'TERMINAL',
                'stateName': state_name.value,
                'enteredTime': TERMINAL_TIME,
                'error': error,
            }
        )
        return event

    def _set_pending(self, request_id: str):
        self._application_table.update_item(
            Key={'pk': f'{COMPACT}#APPLICATION#{APPLICATION_ID}', 'sk': 'APPLICATION'},
            UpdateExpression='SET pendingAction = :pending',
            ExpressionAttributeValues={':pending': {'requestId': request_id}},
        )

    def _captured_logs(self):
        return _CapturedLogs()

    def _assert_token_absent(self, result: dict, captured: _LogCapture):
        self.assertNotIn(CALLBACK_VALUE, json.dumps(result))
        self.assertNotIn(CALLBACK_VALUE, '\n'.join(captured.messages))


class _CapturedLogs:
    def __enter__(self):
        self._previous_level = logger.level
        self._capture = _LogCapture()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(self._capture)
        return self._capture

    def __exit__(self, exc_type, exc, traceback):
        logger.removeHandler(self._capture)
        logger.setLevel(self._previous_level)
        return False
