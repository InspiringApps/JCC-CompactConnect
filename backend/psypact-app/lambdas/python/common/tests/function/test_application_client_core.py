import os

import boto3
from cc_common.applicants.application_client import task_token_hash
from cc_common.applicants.application_state import SectionName, StateName
from cc_common.psypact_config import PsypactConfig
from common_lambdas.exceptions import CCConflictException, CCNotFoundException
from moto import mock_aws

from tests.function import TstFunction

# These are opaque callback identifiers, not credentials.

COMPACT = 'psypact'
APPLICATION_ID = 'app-1'
PROVIDER_ID = 'provider-1'
EXECUTION_ARN = 'arn:aws:states:us-east-1:000000000000:execution:ApplicationWorkflow:app-1-g1'
OTHER_ARN = 'arn:aws:states:us-east-1:000000000000:execution:ApplicationWorkflow:someone-else'
STARTED_AT = '2026-11-05T00:00:01+00:00'
STAFF_REVIEW_AT = '2026-11-05T00:00:02+00:00'
APPROVED_AT = '2026-11-05T00:00:03+00:00'
TASK_TOKEN = 'task-token-1'  # noqa: S105
STAFF_TASK_TOKEN = 'staff-token'  # noqa: S105


@mock_aws
class TestApplicationClientCore(TstFunction):
    """Moto coverage for application reads, creation, and EnterState writes."""

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

        self.psypact_config = PsypactConfig()
        self.client = self.psypact_config.application_client

    def test_query_all_items_is_not_a_transactional_snapshot(self):
        self.assertIn('not a transactional snapshot', self.client.query_all_items.__doc__)

    def test_get_missing_application_returns_none_and_snapshot_raises(self):
        self.assertIsNone(self.client.get_application(COMPACT, APPLICATION_ID))
        with self.assertRaises(CCNotFoundException):
            self.client.get_snapshot(COMPACT, APPLICATION_ID)

    def test_create_writes_application_and_six_empty_sections(self):
        self._create()

        application = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertEqual(0, int(application['version']))
        self.assertEqual(1, int(application['generation']))
        self.assertEqual(EXECUTION_ARN, application['executionArn'])
        self.assertEqual(PROVIDER_ID, application['providerId'])
        self.assertEqual(['apit'], application['types'])
        self.assertFalse(application['isRenewal'])
        self.assertEqual(f'{COMPACT}#PROVIDER#{PROVIDER_ID}', application['applicantGSIPK'])
        self.assertEqual(APPLICATION_ID, application['applicantGSISK'])
        self.assertNotIn('status', application)

        snapshot = self.client.get_snapshot(COMPACT, APPLICATION_ID)
        self.assertEqual(APPLICATION_ID, snapshot.application['applicationId'])
        self.assertEqual(set(SectionName), set(snapshot.sections))
        for section in SectionName:
            self.assertEqual({}, snapshot.sections[section]['data'])
            self.assertEqual([], snapshot.sections[section]['reviews'])
            self.assertEqual(section.value, snapshot.sections[section]['sectionName'])

        self.assertEqual(7, len(self.client.query_all_items(COMPACT, APPLICATION_ID)))

    def test_create_twice_fails(self):
        self._create()
        with self.assertRaises(CCConflictException):
            self._create()

    def test_enter_state_writes_status_token_gsi_and_audit_item(self):
        self._create()
        stored = self._enter_started()

        self.assertEqual('started', stored['status'])
        self.assertEqual(StateName.STARTED.value, stored['stateName'])
        self.assertEqual(TASK_TOKEN, stored['taskToken'])
        self.assertEqual(task_token_hash(TASK_TOKEN), stored['taskTokenHash'])
        self.assertEqual(1, int(stored['version']))
        self.assertEqual(f'{COMPACT}#STATUS#started', stored['statusGSIPK'])
        self.assertTrue(stored['statusGSISK'].endswith(f'#{APPLICATION_ID}'))
        self.assertEqual(f'{COMPACT}#ACTOR#{PROVIDER_ID}', stored['actorGSIPK'])
        self.assertEqual(f'started#{APPLICATION_ID}', stored['actorGSISK'])
        self.assertNotIn('pendingAction', stored)

        audit = self._audit_item(STARTED_AT, StateName.STARTED)
        self.assertEqual(StateName.STARTED.value, audit['toState'])
        self.assertEqual(STARTED_AT, audit['enteredTime'])
        self.assertEqual(EXECUTION_ARN, audit['executionArn'])

    def test_exact_replay_is_a_no_op(self):
        self._create()
        first = self._enter_started()
        second = self._enter_started()

        self.assertEqual(first['version'], second['version'])
        self.assertEqual(first['taskTokenHash'], second['taskTokenHash'])
        self.assertEqual(first['dateOfUpdate'], second['dateOfUpdate'])
        self.assertEqual(1, len(self._audits()))

    def test_replay_does_not_clear_pending_action_from_a_later_request(self):
        self._create()
        self._enter_started()
        self._application_table.update_item(
            Key=self._application_key(),
            UpdateExpression='SET pendingAction = :pending',
            ExpressionAttributeValues={':pending': {'requestId': 'later-request'}},
        )

        replayed = self._enter_started()

        self.assertEqual('later-request', replayed['pendingAction']['requestId'])
        self.assertEqual(1, int(replayed['version']))

    def test_wrong_execution_arn_is_rejected(self):
        self._create()
        with self.assertRaises(CCConflictException):
            self.client.enter_state(
                COMPACT,
                APPLICATION_ID,
                execution_arn=OTHER_ARN,
                state_name=StateName.STARTED,
                entered_time=STARTED_AT,
                task_token=TASK_TOKEN,
            )

        application = self.client.get_application(COMPACT, APPLICATION_ID)
        self.assertNotIn('status', application)
        self.assertNotIn('lastEnteredKey', application)

    def test_terminal_state_removes_token_and_actor_and_sets_completed(self):
        self._create()
        self._enter_started()
        stored = self.client.enter_state(
            COMPACT,
            APPLICATION_ID,
            execution_arn=EXECUTION_ARN,
            state_name=StateName.APPROVED,
            entered_time=APPROVED_AT,
            task_token=None,
            terminal=True,
        )

        self.assertEqual('approved', stored['status'])
        self.assertEqual(f'{EXECUTION_ARN}#{APPROVED_AT}#{StateName.APPROVED.value}', stored['lastEnteredKey'])
        self.assertIn('completed', stored)
        self.assertNotIn('taskToken', stored)
        self.assertNotIn('taskTokenHash', stored)
        self.assertNotIn('actorGSIPK', stored)
        self.assertNotIn('actorGSISK', stored)
        self.assertEqual(f'{COMPACT}#STATUS#approved', stored['statusGSIPK'])
        self.assertEqual(2, int(stored['version']))
        self.assertEqual(StateName.STARTED.value, self._audit_item(APPROVED_AT, StateName.APPROVED)['fromState'])

    def test_terminal_deactivation_records_reason(self):
        self._create()
        stored = self.client.enter_state(
            COMPACT,
            APPLICATION_ID,
            execution_arn=EXECUTION_ARN,
            state_name=StateName.DEACTIVATED,
            entered_time=APPROVED_AT,
            task_token=None,
            terminal=True,
            reason='TIMEOUT',
        )

        self.assertEqual('deactivated', stored['status'])
        self.assertEqual('TIMEOUT', stored['deactivationReason'])
        self.assertIn('completed', stored)
        self.assertNotIn('taskToken', stored)

    def test_reviewer_state_sets_actor_gsi_to_the_assigned_sub(self):
        self._create()
        self._application_table.update_item(
            Key=self._application_key(),
            UpdateExpression='SET firstReviewerSub = :sub',
            ExpressionAttributeValues={':sub': 'reviewer-1'},
        )

        stored = self.client.enter_state(
            COMPACT,
            APPLICATION_ID,
            execution_arn=EXECUTION_ARN,
            state_name=StateName.FIRST_REVIEW,
            entered_time='2026-11-05T00:00:04+00:00',
            task_token=TASK_TOKEN,
        )

        self.assertEqual('first-review', stored['status'])
        self.assertEqual(f'{COMPACT}#ACTOR#reviewer-1', stored['actorGSIPK'])
        self.assertEqual(f'first-review#{APPLICATION_ID}', stored['actorGSISK'])

    def test_staff_review_removes_actor_gsi_and_matching_reopen_lock(self):
        self._create()
        self._enter_started()
        self._application_table.update_item(
            Key=self._application_key(),
            UpdateExpression='SET reopenLock = :lock',
            ExpressionAttributeValues={
                ':lock': {'requestId': 'reopen-1', 'oldGeneration': 1, 'oldExecutionArn': 'arn:old'}
            },
        )

        stored = self.client.enter_state(
            COMPACT,
            APPLICATION_ID,
            execution_arn=EXECUTION_ARN,
            state_name=StateName.STAFF_REVIEW,
            entered_time=STAFF_REVIEW_AT,
            task_token=STAFF_TASK_TOKEN,  # noqa: S106
        )

        self.assertEqual('staff-review', stored['status'])
        self.assertNotIn('actorGSIPK', stored)
        self.assertNotIn('actorGSISK', stored)
        self.assertNotIn('reopenLock', stored)
        self.assertEqual(STAFF_TASK_TOKEN, stored['taskToken'])

    def test_replay_does_not_clear_a_reopen_lock_set_later(self):
        self._create()
        self.client.enter_state(
            COMPACT,
            APPLICATION_ID,
            execution_arn=EXECUTION_ARN,
            state_name=StateName.STAFF_REVIEW,
            entered_time=STAFF_REVIEW_AT,
            task_token=STAFF_TASK_TOKEN,  # noqa: S106
        )
        self._application_table.update_item(
            Key=self._application_key(),
            UpdateExpression='SET reopenLock = :lock',
            ExpressionAttributeValues={':lock': {'requestId': 'later-reopen'}},
        )

        replayed = self.client.enter_state(
            COMPACT,
            APPLICATION_ID,
            execution_arn=EXECUTION_ARN,
            state_name=StateName.STAFF_REVIEW,
            entered_time=STAFF_REVIEW_AT,
            task_token=STAFF_TASK_TOKEN,  # noqa: S106
        )

        self.assertEqual('later-reopen', replayed['reopenLock']['requestId'])

    def test_decision_reads_use_consistent_read(self):
        recorded = []
        dynamodb = self.psypact_config.dynamodb_client
        real_get_item = dynamodb.get_item
        real_query = dynamodb.query
        real_transact_get = dynamodb.transact_get_items

        def get_item(**kwargs):
            recorded.append(('get_item', kwargs))
            return real_get_item(**kwargs)

        def query(**kwargs):
            recorded.append(('query', kwargs))
            return real_query(**kwargs)

        def transact_get_items(**kwargs):
            recorded.append(('transact_get_items', kwargs))
            return real_transact_get(**kwargs)

        dynamodb.get_item = get_item
        dynamodb.query = query
        dynamodb.transact_get_items = transact_get_items

        self._create()
        self.client.get_application(COMPACT, APPLICATION_ID)
        self.client.get_snapshot(COMPACT, APPLICATION_ID)
        self.client.query_all_items(COMPACT, APPLICATION_ID)
        self._enter_started()
        self._enter_started()

        decision_reads = [kwargs for name, kwargs in recorded if name in {'get_item', 'query'}]
        self.assertGreaterEqual(len(decision_reads), 1)
        for kwargs in decision_reads:
            self.assertTrue(kwargs.get('ConsistentRead'))
            self.assertNotIn('IndexName', kwargs)
        self.assertTrue(any(name == 'transact_get_items' for name, _kwargs in recorded))

    def _create(self):
        return self.client.create_application(
            COMPACT,
            APPLICATION_ID,
            execution_arn=EXECUTION_ARN,
            schedule_name='app-1-g1',
            workflow_expires_at='2027-11-04T23:00:00+00:00',
            provider_id=PROVIDER_ID,
            types=['apit'],
            is_renewal=False,
            created='2026-11-05T00:00:00+00:00',
        )

    def _enter_started(self):
        return self.client.enter_state(
            COMPACT,
            APPLICATION_ID,
            execution_arn=EXECUTION_ARN,
            state_name=StateName.STARTED,
            entered_time=STARTED_AT,
            task_token=TASK_TOKEN,
        )

    def _application_key(self):
        return {'pk': self.client.pk(COMPACT, APPLICATION_ID), 'sk': 'APPLICATION'}

    def _audit_item(self, entered_time: str, state_name: StateName) -> dict:
        response = self._application_table.get_item(
            Key={
                'pk': self.client.pk(COMPACT, APPLICATION_ID),
                'sk': self.client.transition_sk(entered_time, state_name),
            }
        )
        return response['Item']

    def _audits(self) -> list[dict]:
        return [
            item
            for item in self.client.query_all_items(COMPACT, APPLICATION_ID)
            if str(item['sk']).startswith('TRANSITION#')
        ]
