import json
import os
from unittest.mock import MagicMock

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from cc_common.applicants.application_state import (
    ApplicationStatus,
    Caller,
    ReviewSectionStatus,
    SectionName,
    StateName,
    WorkflowAction,
    is_terminal,
)
from cc_common.applicants.application_transition_service import ApplicationTransitionService
from cc_common.applicants.application_workflow_client import (
    ApplicationWorkflowClient,
    CallbackDelivery,
    WorkflowStartAmbiguous,
)
from cc_common.config import logger, metrics
from cc_common.psypact_config import PsypactConfig
from common_lambdas.exceptions import CCAccessDeniedException, CCConflictException, CCInvalidRequestException
from moto import mock_aws

from tests import TstLambdas

COMPACT = 'psypact'
APPLICATION_ID = 'app-1'
PROVIDER_ID = 'provider-1'
EXPIRES = '2027-11-05T00:00:00+00:00'
CREATED = '2026-11-05T00:00:00+00:00'
CALLBACK = 'callback-value'
FIRST = 'reviewer-first'
SECOND = 'reviewer-second'
APPLICANT = Caller(sub='applicant-sub', scopes=set(), provider_id=PROVIDER_ID)
OTHER_APPLICANT = Caller(sub='other-sub', scopes=set(), provider_id='someone-else')
ADMIN = Caller(sub='admin-sub', scopes={'psypact/admin'})
FIRST_REVIEWER = Caller(sub=FIRST, scopes={'psypact/admin'})


def _client_error(code: str, operation: str = 'SendTaskSuccess', status: int = 400) -> ClientError:
    return ClientError(
        {'Error': {'Code': code, 'Message': code}, 'ResponseMetadata': {'HTTPStatusCode': status}},
        operation,
    )


class TestApplicationWorkflowClient(TstLambdas):
    def setUp(self):  # noqa: N801 invalid-name
        super().setUp()
        self.sfn = MagicMock()
        self.workflow = ApplicationWorkflowClient(os.environ['APPLICATION_STATE_MACHINE_ARN'], self.sfn)

    def test_execution_name_is_deterministic_and_restricted(self):
        self.assertEqual('app-1-g1', self.workflow.execution_name(APPLICATION_ID, 1))
        self.assertEqual(
            'arn:aws:states:us-east-1:000000000000:execution:ApplicationWorkflow:app-1-g1',
            self.workflow.execution_arn(COMPACT, APPLICATION_ID, 1),
        )
        self.assertEqual(
            'arn:aws:states:us-east-1:000000000000:execution:ApplicationWorkflow:' + ('a' * 77) + '-g1',
            self.workflow.execution_arn(COMPACT, 'a' * 77, 1),
        )
        with self.assertRaises(CCInvalidRequestException):
            self.workflow.execution_arn(COMPACT, 'a' * 78, 1)
        with self.assertRaises(CCInvalidRequestException):
            self.workflow.execution_name('app 1', 1)

    def test_start_execution_retries_are_byte_identical(self):
        self.sfn.start_execution.return_value = {'executionArn': 'arn:execution'}
        kwargs = self._start_kwargs()
        self.workflow.start_execution(**kwargs)
        self.workflow.start_execution(**kwargs)

        first = self.sfn.start_execution.call_args_list[0].kwargs['input']
        second = self.sfn.start_execution.call_args_list[1].kwargs['input']
        self.assertEqual(first, second)
        self.assertEqual(
            {
                'applicationId': APPLICATION_ID,
                'compact': COMPACT,
                'generation': 1,
                'startAt': StateName.STARTED.value,
                'workflowExpiresAt': EXPIRES,
            },
            json.loads(first),
        )
        self.assertLess(first.index('applicationId'), first.index('compact'))

    def test_existing_execution_with_the_same_input_is_success(self):
        body = self.workflow.execution_input(**self._start_kwargs())
        self.sfn.start_execution.side_effect = _client_error('ExecutionAlreadyExists', 'StartExecution')
        self.sfn.describe_execution.return_value = {'input': body, 'status': 'RUNNING'}

        described = self.workflow.start_execution(**self._start_kwargs())

        self.assertEqual('RUNNING', described['status'])

    def test_existing_execution_with_different_input_conflicts(self):
        self.sfn.start_execution.side_effect = _client_error('ExecutionAlreadyExists', 'StartExecution')
        self.sfn.describe_execution.return_value = {'input': '{"compact":"other"}', 'status': 'RUNNING'}

        with self.assertRaises(CCConflictException):
            self.workflow.start_execution(**self._start_kwargs())

    def test_send_task_success_classifies_retryable_stale_and_unknown_errors(self):
        self.sfn.send_task_success.side_effect = _client_error('ThrottlingException')
        self.assertEqual(CallbackDelivery.RETRYABLE, self.workflow.send_task_success(CALLBACK, {'action': 'SUBMIT'}))

        self.sfn.send_task_success.side_effect = _client_error('InternalFailure', status=500)
        self.assertEqual(CallbackDelivery.RETRYABLE, self.workflow.send_task_success(CALLBACK, {'action': 'SUBMIT'}))

        self.sfn.send_task_success.side_effect = BotoCoreError()
        self.assertEqual(CallbackDelivery.RETRYABLE, self.workflow.send_task_success(CALLBACK, {'action': 'SUBMIT'}))

        self.sfn.send_task_success.side_effect = _client_error('InvalidToken')
        self.assertEqual(CallbackDelivery.STALE, self.workflow.send_task_success(CALLBACK, {'action': 'SUBMIT'}))

        self.sfn.send_task_success.side_effect = _client_error('ValidationException')
        with self.assertRaises(ClientError):
            self.workflow.send_task_success(CALLBACK, {'action': 'SUBMIT'})

    def _start_kwargs(self) -> dict:
        return {
            'compact': COMPACT,
            'application_id': APPLICATION_ID,
            'generation': 1,
            'workflow_expires_at': EXPIRES,
            'start_at': StateName.STARTED.value,
        }


@mock_aws
class TestApplicationTransitionService(TstLambdas):
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
        self.psypact_config = PsypactConfig()
        self.client = self.psypact_config.application_client
        self.sfn = MagicMock()
        self.workflow = ApplicationWorkflowClient(os.environ['APPLICATION_STATE_MACHINE_ARN'], self.sfn)
        self.service = ApplicationTransitionService(
            self.psypact_config,
            workflow_client=self.workflow,
            sleeper=lambda _seconds: None,
            poll_timeout_seconds=0,
            backoff_seconds=0,
        )

    def test_submit_reaches_staff_review(self):
        self._create()
        self._enter(StateName.STARTED)
        self._accept_and_enter(StateName.STAFF_REVIEW)

        result = self.service.submit_or_transition(COMPACT, APPLICATION_ID, APPLICANT, WorkflowAction.SUBMIT, 'req-1')

        self.assertFalse(result.pending)
        self.assertTrue(result.accepted)
        self.assertEqual(ApplicationStatus.STAFF_REVIEW.value, result.status)
        output = json.loads(self.sfn.send_task_success.call_args.kwargs['output'])
        self.assertEqual(
            {'action': 'SUBMIT', 'actorSub': APPLICANT.sub, 'requestId': 'req-1'},
            output,
        )

    def test_advance_reaches_second_review_and_records_the_review(self):
        self._ready_for_first_review()
        self._accept_and_enter(StateName.SECOND_REVIEW)

        result = self.service.submit_or_transition(
            COMPACT,
            APPLICATION_ID,
            FIRST_REVIEWER,
            WorkflowAction.ADVANCE,
            'req-advance',
            notes_for_applicant='Ready for the next reviewer',
            reviewer_selected_application_status=ApplicationStatus.APPROVED.value,
        )

        self.assertEqual(ApplicationStatus.SECOND_REVIEW.value, result.status)
        reviews = self.client.get_application(COMPACT, APPLICATION_ID)['reviews']
        first_review = next(review for review in reviews if review['reviewer']['id'] == FIRST)
        self.assertEqual('Ready for the next reviewer', first_review['notesForApplicant'])
        self.assertEqual(ApplicationStatus.APPROVED.value, first_review['reviewerSelectedApplicationStatus'])
        self.assertIn('reviewCompletionDate', first_review)

    def test_unauthorized_caller_is_rejected_before_delivery(self):
        self._create()
        self._enter(StateName.STARTED)

        with self.assertRaises(CCAccessDeniedException):
            self.service.submit_or_transition(
                COMPACT,
                APPLICATION_ID,
                OTHER_APPLICANT,
                WorkflowAction.SUBMIT,
                'req-denied',
            )

        self.sfn.send_task_success.assert_not_called()
        self.assertNotIn('pendingAction', self.client.get_application(COMPACT, APPLICATION_ID))

    def test_illegal_action_is_rejected(self):
        self._create()
        self._enter(StateName.STARTED)

        with self.assertRaises(CCInvalidRequestException):
            self.service.submit_or_transition(COMPACT, APPLICATION_ID, APPLICANT, WorkflowAction.ADVANCE, 'req-bad')

        self.sfn.send_task_success.assert_not_called()

    def test_incomplete_reviews_are_rejected(self):
        self._ready_for_first_review(complete_reviews=False)

        with self.assertRaises(CCInvalidRequestException):
            self.service.submit_or_transition(
                COMPACT,
                APPLICATION_ID,
                FIRST_REVIEWER,
                WorkflowAction.ADVANCE,
                'req-incomplete',
            )

        self.sfn.send_task_success.assert_not_called()
        self.assertNotIn('pendingAction', self.client.get_application(COMPACT, APPLICATION_ID))

    def test_a_second_transition_conflicts_while_the_first_is_pending(self):
        self._create()
        self._enter(StateName.STARTED)

        def send(**_kwargs):
            with self.assertRaises(CCConflictException):
                self.service.submit_or_transition(
                    COMPACT,
                    APPLICATION_ID,
                    APPLICANT,
                    WorkflowAction.SUBMIT,
                    'req-other',
                )
            self._enter(StateName.STAFF_REVIEW)
            return {}

        self.sfn.send_task_success.side_effect = send
        result = self.service.submit_or_transition(COMPACT, APPLICATION_ID, APPLICANT, WorkflowAction.SUBMIT, 'req-1')
        self.assertEqual(ApplicationStatus.STAFF_REVIEW.value, result.status)

    def test_delivery_retries_then_succeeds(self):
        self._create()
        self._enter(StateName.STARTED)
        calls = {'count': 0}

        def send(**_kwargs):
            calls['count'] += 1
            if calls['count'] == 1:
                raise _client_error('ThrottlingException')
            self._enter(StateName.STAFF_REVIEW)
            return {}

        self.sfn.send_task_success.side_effect = send
        result = self.service.submit_or_transition(COMPACT, APPLICATION_ID, APPLICANT, WorkflowAction.SUBMIT, 'req-1')

        self.assertEqual(2, calls['count'])
        self.assertEqual(ApplicationStatus.STAFF_REVIEW.value, result.status)
        self.assertFalse(result.pending)

    def test_ambiguous_error_after_advancement_returns_success(self):
        self._create()
        self._enter(StateName.STARTED)

        def send(**_kwargs):
            self._enter(StateName.STAFF_REVIEW)
            raise _client_error('ServiceUnavailable', status=503)

        self.sfn.send_task_success.side_effect = send
        result = self.service.submit_or_transition(COMPACT, APPLICATION_ID, APPLICANT, WorkflowAction.SUBMIT, 'req-1')

        self.assertEqual(1, self.sfn.send_task_success.call_count)
        self.assertEqual(ApplicationStatus.STAFF_REVIEW.value, result.status)
        self.assertTrue(result.accepted)
        self.assertFalse(result.pending)

    def test_exhausted_retries_keep_the_pending_action(self):
        self._create()
        self._enter(StateName.STARTED)
        self.sfn.send_task_success.side_effect = _client_error('ThrottlingException')

        with self.assertLogs(logger.name, level='ERROR') as captured:
            result = self.service.submit_or_transition(
                COMPACT,
                APPLICATION_ID,
                APPLICANT,
                WorkflowAction.SUBMIT,
                'req-stuck',
            )

        self.assertEqual(3, self.sfn.send_task_success.call_count)
        self.assertTrue(result.pending)
        self.assertFalse(result.accepted)
        self.assertEqual(ApplicationStatus.STAFF_REVIEW.value, result.expected_status)
        stored = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual('req-stuck', stored['pendingAction']['requestId'])
        self.assertEqual(3, int(stored['pendingAction']['attempts']))
        self.assertIn(APPLICATION_ID, '\n'.join(captured.output))
        self.assertIn('req-stuck', '\n'.join(captured.output))
        self.assertIn('ApplicationCallbackDeliveryExhausted', metrics.metric_set)

    def test_stale_token_with_advanced_state_returns_the_stored_result(self):
        self._create()
        self._enter(StateName.STARTED)

        def send(**_kwargs):
            self._enter(StateName.STAFF_REVIEW)
            raise _client_error('InvalidToken')

        self.sfn.send_task_success.side_effect = send
        result = self.service.submit_or_transition(COMPACT, APPLICATION_ID, APPLICANT, WorkflowAction.SUBMIT, 'req-1')
        repeated = self.service.submit_or_transition(
            COMPACT,
            APPLICATION_ID,
            APPLICANT,
            WorkflowAction.SUBMIT,
            'req-1',
        )

        self.assertEqual(ApplicationStatus.STAFF_REVIEW.value, result.status)
        self.assertEqual(result.as_dict(), repeated.as_dict())
        self.assertEqual(1, self.sfn.send_task_success.call_count)
        self.assertNotIn('pendingAction', self.client.get_application(COMPACT, APPLICATION_ID))

    def test_same_request_resumes_and_a_different_request_conflicts(self):
        self._create()
        self._enter(StateName.STARTED)
        self.sfn.send_task_success.return_value = {}

        first = self.service.submit_or_transition(COMPACT, APPLICATION_ID, APPLICANT, WorkflowAction.SUBMIT, 'req-1')
        self.assertTrue(first.pending)
        self.assertTrue(first.accepted)
        with self.assertRaises(CCConflictException):
            self.service.submit_or_transition(COMPACT, APPLICATION_ID, APPLICANT, WorkflowAction.SUBMIT, 'req-2')
        with self.assertRaises(CCConflictException):
            self.service.resume_delivery(COMPACT, APPLICATION_ID, 'req-2')

        resumed = self.service.resume_delivery(COMPACT, APPLICATION_ID, 'req-1')
        self.assertTrue(resumed.pending)
        self.assertEqual(2, self.sfn.send_task_success.call_count)
        self.assertEqual('req-1', self.client.get_application(COMPACT, APPLICATION_ID)['pendingAction']['requestId'])

    def test_replay_rejects_a_different_caller_or_action_before_delivery(self):
        self._create()
        self._enter(StateName.STARTED)
        self.sfn.send_task_success.return_value = {}

        pending = self.service.submit_or_transition(
            COMPACT,
            APPLICATION_ID,
            APPLICANT,
            WorkflowAction.SUBMIT,
            'req-1',
        )
        self.assertTrue(pending.pending)
        sends_before = self.sfn.send_task_success.call_count

        with self.assertRaises(CCConflictException):
            self.service.submit_or_transition(
                COMPACT,
                APPLICATION_ID,
                OTHER_APPLICANT,
                WorkflowAction.SUBMIT,
                'req-1',
            )
        with self.assertRaises(CCConflictException):
            self.service.submit_or_transition(
                COMPACT,
                APPLICATION_ID,
                APPLICANT,
                WorkflowAction.ADVANCE,
                'req-1',
            )
        self.assertEqual(sends_before, self.sfn.send_task_success.call_count)

        retried = self.service.submit_or_transition(
            COMPACT,
            APPLICATION_ID,
            APPLICANT,
            WorkflowAction.SUBMIT,
            'req-1',
        )
        self.assertTrue(retried.accepted)
        self.assertEqual(sends_before + 1, self.sfn.send_task_success.call_count)

    def test_stored_replay_rejects_a_different_caller_or_action(self):
        self._create()
        self._enter(StateName.STARTED)

        def send(**_kwargs):
            self._enter(StateName.STAFF_REVIEW)
            raise _client_error('InvalidToken')

        self.sfn.send_task_success.side_effect = send
        result = self.service.submit_or_transition(COMPACT, APPLICATION_ID, APPLICANT, WorkflowAction.SUBMIT, 'req-1')
        self.sfn.send_task_success.side_effect = None

        with self.assertRaises(CCConflictException):
            self.service.submit_or_transition(
                COMPACT,
                APPLICATION_ID,
                OTHER_APPLICANT,
                WorkflowAction.SUBMIT,
                'req-1',
            )
        with self.assertRaises(CCConflictException):
            self.service.submit_or_transition(
                COMPACT,
                APPLICATION_ID,
                APPLICANT,
                WorkflowAction.ADVANCE,
                'req-1',
            )

        repeated = self.service.submit_or_transition(
            COMPACT,
            APPLICATION_ID,
            APPLICANT,
            WorkflowAction.SUBMIT,
            'req-1',
        )
        self.assertEqual(result.as_dict(), repeated.as_dict())
        self.assertEqual(1, self.sfn.send_task_success.call_count)

    def test_admin_override_sends_the_target_and_rejects_an_unassigned_reviewer_state(self):
        self._create()
        self._enter(StateName.STARTED)
        with self.assertRaises(CCInvalidRequestException):
            self.service.admin_override(COMPACT, APPLICATION_ID, ADMIN, 'req-bad', StateName.FIRST_REVIEW)
        self.sfn.send_task_success.assert_not_called()

        self._accept_and_enter(StateName.STAFF_REVIEW)
        result = self.service.admin_override(COMPACT, APPLICATION_ID, ADMIN, 'req-override', StateName.STAFF_REVIEW)

        self.assertEqual(ApplicationStatus.STAFF_REVIEW.value, result.status)
        output = json.loads(self.sfn.send_task_success.call_args.kwargs['output'])
        self.assertEqual(StateName.STAFF_REVIEW.value, output['targetState'])
        self.assertEqual(WorkflowAction.ADMIN_OVERRIDE.value, output['action'])

    def test_create_starts_after_the_schedule_and_an_ambiguous_start_keeps_the_application(self):
        order = []

        def schedule(**kwargs):
            order.append(kwargs['schedule_name'])

        def start(**_kwargs):
            order.append('start')
            self._enter(StateName.STARTED)
            return {'executionArn': self.workflow.execution_arn(COMPACT, APPLICATION_ID, 1)}

        service = ApplicationTransitionService(
            self.psypact_config,
            workflow_client=self.workflow,
            schedule_creator=schedule,
            sleeper=lambda _seconds: None,
            poll_timeout_seconds=0,
            backoff_seconds=0,
        )
        self.sfn.start_execution.side_effect = start
        result = service.create_application_and_start(
            COMPACT,
            APPLICATION_ID,
            provider_id=PROVIDER_ID,
            types=['apit'],
            is_renewal=False,
            created=CREATED,
            workflow_expires_at=EXPIRES,
        )

        self.assertEqual(['app-1-g1', 'start'], order)
        self.assertEqual(ApplicationStatus.STARTED.value, result.status)
        self.assertEqual(
            self.workflow.execution_arn(COMPACT, APPLICATION_ID, 1),
            self.client.get_application(COMPACT, APPLICATION_ID)['executionArn'],
        )

        self.sfn.start_execution.side_effect = _client_error('ThrottlingException', 'StartExecution')
        body = self.workflow.execution_input(
            compact=COMPACT,
            application_id='app-2',
            generation=1,
            workflow_expires_at=EXPIRES,
            start_at=StateName.STARTED.value,
        )
        self.sfn.describe_execution.return_value = {'input': body, 'status': 'RUNNING'}
        ambiguous = service.create_application_and_start(
            COMPACT,
            'app-2',
            provider_id=PROVIDER_ID,
            types=['apit'],
            is_renewal=False,
            created=CREATED,
            workflow_expires_at=EXPIRES,
        )
        self.assertTrue(ambiguous.pending)
        self.assertIsNotNone(self.client.get_application(COMPACT, 'app-2'))

        self.sfn.describe_execution.side_effect = _client_error('ExecutionDoesNotExist', 'DescribeExecution')
        with self.assertRaises(WorkflowStartAmbiguous):
            service.create_application_and_start(
                COMPACT,
                'app-3',
                provider_id=PROVIDER_ID,
                types=['apit'],
                is_renewal=False,
                created=CREATED,
                workflow_expires_at=EXPIRES,
            )
        self.assertIsNotNone(self.client.get_application(COMPACT, 'app-3'))

    def _accept_and_enter(self, state_name: StateName) -> None:
        def send(**_kwargs):
            terminal = is_terminal(state_name)
            self._enter(state_name, terminal=terminal)
            return {}

        self.sfn.send_task_success.side_effect = send

    def _create(self, application_id: str = APPLICATION_ID) -> None:
        self.client.create_application(
            COMPACT,
            application_id,
            execution_arn=self.workflow.execution_arn(COMPACT, application_id, 1),
            schedule_name=f'{application_id}-g1',
            workflow_expires_at=EXPIRES,
            provider_id=PROVIDER_ID,
            types=['apit'],
            is_renewal=False,
            created=CREATED,
        )

    def _enter(self, state_name: StateName, application_id: str = APPLICATION_ID, terminal: bool = False) -> dict:
        self._entered_count += 1
        return self.client.enter_state(
            COMPACT,
            application_id,
            execution_arn=self.workflow.execution_arn(COMPACT, application_id, 1),
            state_name=state_name,
            entered_time=f'2026-11-05T00:01:{self._entered_count:02d}+00:00',
            task_token=None if terminal else CALLBACK,
            terminal=terminal,
        )

    def _ready_for_first_review(self, complete_reviews: bool = True) -> None:
        self._create()
        self._enter(StateName.STAFF_REVIEW)
        version = int(self.client.get_application(COMPACT, APPLICATION_ID)['version'])
        self.client.assign_reviewers(
            COMPACT,
            APPLICATION_ID,
            {'firstReviewerSub': FIRST, 'secondReviewerSub': SECOND},
            expected_version=version,
        )
        self._enter(StateName.FIRST_REVIEW)
        if not complete_reviews:
            return
        for section in SectionName:
            self.client.save_section_review(
                COMPACT,
                APPLICATION_ID,
                section,
                'first-reviewer',
                FIRST,
                ReviewSectionStatus.APPROVED,
            )
