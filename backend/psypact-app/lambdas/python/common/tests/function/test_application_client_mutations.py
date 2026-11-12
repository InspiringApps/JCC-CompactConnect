import os

import boto3
from cc_common.applicants.application_state import (
    FIRST_AND_SECOND_REVIEWER_MUST_DIFFER,
    ActorRole,
    ReviewSectionStatus,
    SectionName,
    StateName,
)
from cc_common.applicants.application_state import ApplicationStatus as StoredStatus
from cc_common.psypact_config import PsypactConfig
from common_lambdas.exceptions import CCConflictException, CCInvalidRequestException
from moto import mock_aws

from tests.function import TstFunction

COMPACT = 'psypact'
APPLICATION_ID = 'app-1'
PROVIDER_ID = 'provider-1'
EXECUTION_ARN = 'arn:aws:states:us-east-1:000000000000:execution:ApplicationWorkflow:app-1-g1'
CALLBACK = 'callback-value'
FIRST = 'reviewer-first'
SECOND = 'reviewer-second'
FINAL = 'reviewer-final'


@mock_aws
class ApplicationTableCase(TstFunction):
    """Moto application table and a client, shared by the mutation tests."""

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

    def _create(self, application_id: str = APPLICATION_ID):
        self.client.create_application(
            COMPACT,
            application_id,
            execution_arn=EXECUTION_ARN,
            schedule_name='app-1-g1',
            workflow_expires_at='2027-11-04T23:00:00+00:00',
            provider_id=PROVIDER_ID,
            types=['apit'],
            is_renewal=False,
            created='2026-11-05T00:00:00+00:00',
        )

    def _enter(self, state_name: StateName, application_id: str = APPLICATION_ID):
        self._entered_count += 1
        return self.client.enter_state(
            COMPACT,
            application_id,
            execution_arn=EXECUTION_ARN,
            state_name=state_name,
            entered_time=f'2026-11-05T00:01:{self._entered_count:02d}+00:00',
            task_token=CALLBACK,
        )

    def _application(self, application_id: str = APPLICATION_ID) -> dict:
        return self.client.get_application(COMPACT, application_id)

    def _staff_then_assign(self, request: dict, application_id: str = APPLICATION_ID):
        self._create(application_id)
        self._enter(StateName.STAFF_REVIEW, application_id)
        version = int(self._application(application_id)['version'])
        return self.client.assign_reviewers(COMPACT, application_id, request, expected_version=version)


@mock_aws
class TestPatchSection(ApplicationTableCase):
    def test_patch_merges_fields_in_started_and_awaiting_applicant_states(self):
        self._create()
        editable_states = [
            StateName.STARTED,
            StateName.AWAITING_APPLICANT_FROM_FIRST,
            StateName.AWAITING_APPLICANT_FROM_SECOND,
            StateName.AWAITING_APPLICANT_FROM_FINAL,
        ]
        for state_name in editable_states:
            with self.subTest(state=state_name.value):
                self._enter(state_name)
                first = self.client.patch_section(
                    COMPACT,
                    APPLICATION_ID,
                    SectionName.PERSONAL_INFORMATION,
                    {'givenName': 'Ada'},
                    actor_provider_id=PROVIDER_ID,
                )
                second = self.client.patch_section(
                    COMPACT,
                    APPLICATION_ID,
                    SectionName.PERSONAL_INFORMATION,
                    {'familyName': 'Lovelace'},
                    actor_provider_id=PROVIDER_ID,
                )
                data = second.sections[SectionName.PERSONAL_INFORMATION]['data']
                self.assertEqual({'givenName': 'Ada', 'familyName': 'Lovelace'}, data)
                self.assertGreater(int(second.application['version']), int(first.application['version']))

    def test_patch_rejected_outside_applicant_states_or_for_another_provider(self):
        self._create()
        self._enter(StateName.FIRST_REVIEW)
        with self.assertRaises(CCConflictException):
            self.client.patch_section(
                COMPACT,
                APPLICATION_ID,
                SectionName.PERSONAL_INFORMATION,
                {'givenName': 'Ada'},
                actor_provider_id=PROVIDER_ID,
            )
        self._create_over_existing_started()
        with self.assertRaises(CCConflictException):
            self.client.patch_section(
                COMPACT,
                APPLICATION_ID,
                SectionName.PERSONAL_INFORMATION,
                {'givenName': 'Ada'},
                actor_provider_id='someone-else',
            )
        self.assertNotIn('givenName', self._section_data())

    def test_patch_rejected_with_pending_action_or_reopen_lock(self):
        self._create()
        self._enter(StateName.STARTED)
        version = int(self._application()['version'])
        self.client.begin_transition(
            COMPACT,
            APPLICATION_ID,
            expected_version=version,
            expected_state_name=StateName.STARTED,
            pending_action=_pending('req-lock'),
        )
        with self.assertRaises(CCConflictException):
            self.client.patch_section(
                COMPACT,
                APPLICATION_ID,
                SectionName.PERSONAL_INFORMATION,
                {'givenName': 'Ada'},
                actor_provider_id=PROVIDER_ID,
            )

        self.client.clear_pending_action(COMPACT, APPLICATION_ID, 'req-lock')
        self._application_table.update_item(
            Key={'pk': self.client.pk(COMPACT, APPLICATION_ID), 'sk': 'APPLICATION'},
            UpdateExpression='SET reopenLock = :lock',
            ExpressionAttributeValues={':lock': {'requestId': 'reopen-1'}},
        )
        with self.assertRaises(CCConflictException):
            self.client.patch_section(
                COMPACT,
                APPLICATION_ID,
                SectionName.PERSONAL_INFORMATION,
                {'givenName': 'Ada'},
                actor_provider_id=PROVIDER_ID,
            )

    def _create_over_existing_started(self):
        """Move the existing application back to Started for the next rejection check."""
        self._enter(StateName.STARTED)

    def _section_data(self) -> dict:
        snapshot = self.client.get_snapshot(COMPACT, APPLICATION_ID)
        return snapshot.sections[SectionName.PERSONAL_INFORMATION]['data']


@mock_aws
class TestAssignReviewers(ApplicationTableCase):
    def test_assignment_creates_shells_and_pending_section_reviews(self):
        result = self._staff_then_assign({'firstReviewerSub': FIRST, 'firstReviewerFirstName': 'Ada'})

        self.assertFalse(result.all_reviewers_set)
        application_review = result.snapshot.application['reviews'][0]
        self.assertEqual(FIRST, application_review['reviewer']['id'])
        self.assertEqual('first-reviewer', application_review['reviewerType'])
        assignment_id = application_review['assignmentId']
        for section in SectionName:
            reviews = result.snapshot.sections[section]['reviews']
            self.assertEqual(1, len(reviews))
            self.assertEqual(assignment_id, reviews[0]['assignmentId'])
            self.assertEqual(ReviewSectionStatus.PENDING.value, reviews[0]['reviewerSelectedApplicationSectionStatus'])

        completed = self.client.assign_reviewers(
            COMPACT,
            APPLICATION_ID,
            {'secondReviewerSub': SECOND, 'finalReviewerSub': FINAL},
            expected_version=int(result.snapshot.application['version']),
        )
        self.assertTrue(completed.all_reviewers_set)
        self.assertEqual(3, len(completed.snapshot.application['reviews']))

    def test_first_equal_to_second_is_rejected_and_final_may_match_either(self):
        result = self._staff_then_assign({'firstReviewerSub': FIRST})
        with self.assertRaises(CCInvalidRequestException) as raised:
            self.client.assign_reviewers(
                COMPACT,
                APPLICATION_ID,
                {'secondReviewerSub': FIRST},
                expected_version=int(result.snapshot.application['version']),
            )
        self.assertEqual(FIRST_AND_SECOND_REVIEWER_MUST_DIFFER, raised.exception.message)

        matched_first = self.client.assign_reviewers(
            COMPACT,
            APPLICATION_ID,
            {'secondReviewerSub': SECOND, 'finalReviewerSub': FIRST},
            expected_version=int(result.snapshot.application['version']),
        )
        self.assertEqual(FIRST, matched_first.snapshot.application['assignedFinalReviewerMetadata']['cognitoSub'])
        self.assertEqual(SECOND, matched_first.snapshot.application['assignedSecondReviewerMetadata']['cognitoSub'])

        matched_second = self._staff_then_assign(
            {'firstReviewerSub': FIRST, 'secondReviewerSub': SECOND, 'finalReviewerSub': SECOND},
            application_id='app-2',
        )
        self.assertEqual(SECOND, matched_second.snapshot.application['assignedFinalReviewerMetadata']['cognitoSub'])
        self.assertEqual(FIRST, matched_second.snapshot.application['assignedFirstReviewerMetadata']['cognitoSub'])

    def test_reassignment_keeps_old_reviews_and_refreshes_actor_gsi(self):
        assigned = self._staff_then_assign({'firstReviewerSub': FIRST})
        self._enter(StateName.FIRST_REVIEW)
        previous_id = assigned.snapshot.application['assignedFirstReviewerMetadata']['assignmentId']
        version = int(self._application()['version'])

        reassigned = self.client.assign_reviewers(
            COMPACT,
            APPLICATION_ID,
            {'firstReviewerSub': 'reviewer-new'},
            expected_version=version,
        )

        application = reassigned.snapshot.application
        self.assertNotEqual(previous_id, application['assignedFirstReviewerMetadata']['assignmentId'])
        self.assertEqual(2, len(application['reviews']))
        self.assertEqual(previous_id, application['reviews'][0]['assignmentId'])
        section_reviews = reassigned.snapshot.sections[SectionName.PERSONAL_INFORMATION]['reviews']
        self.assertEqual(
            [previous_id, application['assignedFirstReviewerMetadata']['assignmentId']],
            [review['assignmentId'] for review in section_reviews],
        )
        self.assertEqual(f'{COMPACT}#ACTOR#reviewer-new', application['actorGSIPK'])
        self.assertTrue(application['actorGSISK'].endswith(f'#{APPLICATION_ID}'))

    def test_concurrent_opposite_role_assignment_of_the_same_user_allows_one(self):
        self._create()
        self._enter(StateName.STAFF_REVIEW)
        version = int(self._application()['version'])
        real_transact = self.client.config.dynamodb_client.transact_write_items

        def wrapped(**kwargs):
            if not getattr(wrapped, 'injected', False):
                wrapped.injected = True
                self.client.config.dynamodb_client.transact_write_items = real_transact
                self.client.assign_reviewers(
                    COMPACT,
                    APPLICATION_ID,
                    {'secondReviewerSub': FIRST},
                    expected_version=version,
                )
            return real_transact(**kwargs)

        self.client.config.dynamodb_client.transact_write_items = wrapped
        with self.assertRaises(CCConflictException):
            self.client.assign_reviewers(
                COMPACT,
                APPLICATION_ID,
                {'firstReviewerSub': FIRST},
                expected_version=version,
            )

        application = self._application()
        self.assertEqual(FIRST, application['assignedSecondReviewerMetadata']['cognitoSub'])
        self.assertNotIn('assignedFirstReviewerMetadata', application)

    def test_null_reviewer_field_keeps_the_existing_assignment(self):
        result = self._staff_then_assign({'firstReviewerSub': FIRST, 'secondReviewerSub': SECOND})
        version = int(result.snapshot.application['version'])
        with self.assertRaises(CCInvalidRequestException) as raised:
            self.client.assign_reviewers(
                COMPACT,
                APPLICATION_ID,
                {'firstReviewerSub': None, 'secondReviewerSub': FIRST},
                expected_version=version,
            )
        self.assertEqual(FIRST_AND_SECOND_REVIEWER_MUST_DIFFER, raised.exception.message)
        application = self._application()
        self.assertEqual(FIRST, application['assignedFirstReviewerMetadata']['cognitoSub'])
        self.assertEqual(SECOND, application['assignedSecondReviewerMetadata']['cognitoSub'])

        kept = self.client.assign_reviewers(
            COMPACT,
            APPLICATION_ID,
            {'firstReviewerSub': None, 'finalReviewerSub': FINAL},
            expected_version=version,
        )
        self.assertEqual(FIRST, kept.snapshot.application['assignedFirstReviewerMetadata']['cognitoSub'])
        self.assertEqual(FINAL, kept.snapshot.application['assignedFinalReviewerMetadata']['cognitoSub'])

    def test_distinctness_condition_applies_when_another_role_changes(self):
        self._create()
        self._enter(StateName.STAFF_REVIEW)
        version = int(self._application()['version'])
        real_transact = self.client.config.dynamodb_client.transact_write_items
        captured = {}

        def wrapped(**kwargs):
            captured['items'] = kwargs['TransactItems']
            return real_transact(**kwargs)

        self.client.config.dynamodb_client.transact_write_items = wrapped
        self.client.assign_reviewers(
            COMPACT,
            APPLICATION_ID,
            {'firstReviewerSub': FIRST, 'finalReviewerSub': FINAL},
            expected_version=version,
        )

        condition = captured['items'][0]['Update']['ConditionExpression']
        self.assertIn('assignedSecondReviewerMetadata.cognitoSub <> :distinctSub', condition)


@mock_aws
class TestSectionReviews(ApplicationTableCase):
    def _first_review(self, final_sub=None):
        request = {'firstReviewerSub': FIRST, 'secondReviewerSub': SECOND}
        if final_sub:
            request['finalReviewerSub'] = final_sub
        assigned = self._staff_then_assign(request)
        self._enter(StateName.FIRST_REVIEW)
        return assigned

    def test_sending_reviewer_can_edit_in_committee_and_others_cannot(self):
        self._first_review()
        self._enter(StateName.COMMITTEE_FROM_FIRST)
        saved = self.client.save_section_review(
            COMPACT,
            APPLICATION_ID,
            SectionName.EDUCATION,
            ActorRole.FIRST_REVIEWER,
            FIRST,
            ReviewSectionStatus.APPROVED,
            {'notesForApplicant': 'Looks complete'},
        )
        review = saved.sections[SectionName.EDUCATION]['reviews'][0]
        self.assertEqual(ReviewSectionStatus.APPROVED.value, review['reviewerSelectedApplicationSectionStatus'])
        self.assertEqual('Looks complete', review['notesForApplicant'])
        self.assertIn('reviewCompletionDate', review)

        with self.assertRaises(CCConflictException):
            self.client.save_section_review(
                COMPACT,
                APPLICATION_ID,
                SectionName.EDUCATION,
                ActorRole.SECOND_REVIEWER,
                SECOND,
                ReviewSectionStatus.REJECTED,
            )

    def test_same_sub_edits_only_the_requested_role(self):
        assigned = self._first_review(final_sub=FIRST)
        saved = self.client.save_section_review(
            COMPACT,
            APPLICATION_ID,
            SectionName.PERSONAL_INFORMATION,
            ActorRole.FIRST_REVIEWER,
            FIRST,
            ReviewSectionStatus.APPROVED,
        )
        reviews = saved.sections[SectionName.PERSONAL_INFORMATION]['reviews']
        by_assignment = {review['assignmentId']: review for review in reviews}
        first_id = assigned.snapshot.application['assignedFirstReviewerMetadata']['assignmentId']
        final_id = saved.application['assignedFinalReviewerMetadata']['assignmentId']
        self.assertEqual(
            ReviewSectionStatus.APPROVED.value,
            by_assignment[first_id]['reviewerSelectedApplicationSectionStatus'],
        )
        self.assertEqual(
            ReviewSectionStatus.PENDING.value,
            by_assignment[final_id]['reviewerSelectedApplicationSectionStatus'],
        )
        located = self.client.locate_active_review(saved.application, ActorRole.FINAL_REVIEWER)
        self.assertEqual(final_id, located['assignmentId'])
        self.assertIsNone(located.get('reviewerSelectedApplicationStatus'))

    def test_old_assignment_cannot_edit_after_reassignment(self):
        self._first_review()
        version = int(self._application()['version'])
        self.client.assign_reviewers(
            COMPACT,
            APPLICATION_ID,
            {'firstReviewerSub': 'reviewer-new'},
            expected_version=version,
        )
        with self.assertRaises(CCConflictException):
            self.client.save_section_review(
                COMPACT,
                APPLICATION_ID,
                SectionName.PERSONAL_INFORMATION,
                ActorRole.FIRST_REVIEWER,
                FIRST,
                ReviewSectionStatus.APPROVED,
            )
        saved = self.client.save_section_review(
            COMPACT,
            APPLICATION_ID,
            SectionName.PERSONAL_INFORMATION,
            ActorRole.FIRST_REVIEWER,
            'reviewer-new',
            ReviewSectionStatus.REJECTED,
        )
        current = self.client.locate_active_section_review(
            saved.sections[SectionName.PERSONAL_INFORMATION],
            saved.application,
            ActorRole.FIRST_REVIEWER,
        )
        self.assertEqual(ReviewSectionStatus.REJECTED.value, current['reviewerSelectedApplicationSectionStatus'])

    def test_require_complete_reviews_checks_every_current_section(self):
        assigned = self._first_review()
        snapshot = self.client.get_snapshot(COMPACT, APPLICATION_ID)
        with self.assertRaises(CCInvalidRequestException):
            self.client.require_complete_reviews(snapshot, ActorRole.FIRST_REVIEWER)

        for section in SectionName:
            self.client.save_section_review(
                COMPACT,
                APPLICATION_ID,
                section,
                ActorRole.FIRST_REVIEWER,
                FIRST,
                ReviewSectionStatus.APPROVED,
            )
        complete = self.client.get_snapshot(COMPACT, APPLICATION_ID)
        self.client.require_complete_reviews(complete, ActorRole.FIRST_REVIEWER)
        self.assertEqual(FIRST, assigned.snapshot.application['assignedFirstReviewerMetadata']['cognitoSub'])


@mock_aws
class TestTransitions(ApplicationTableCase):
    def test_begin_transition_wins_once_and_loses_to_a_later_patch(self):
        self._create()
        self._enter(StateName.STARTED)
        version = int(self._application()['version'])
        stored = self.client.begin_transition(
            COMPACT,
            APPLICATION_ID,
            expected_version=version,
            expected_state_name=StateName.STARTED,
            pending_action=_pending('req-1'),
        )
        self.assertEqual('req-1', stored['pendingAction']['requestId'])
        self.assertIn('submitted', stored)
        self.assertEqual(version + 1, int(stored['version']))
        with self.assertRaises(CCConflictException):
            self.client.begin_transition(
                COMPACT,
                APPLICATION_ID,
                expected_version=version,
                expected_state_name=StateName.STARTED,
                pending_action=_pending('req-2'),
            )

        self.client.clear_pending_action(COMPACT, APPLICATION_ID, 'req-1')
        seen = self.client.get_snapshot(COMPACT, APPLICATION_ID)
        self.client.patch_section(
            COMPACT,
            APPLICATION_ID,
            SectionName.HOME_STATE,
            {'state': 'oh'},
            actor_provider_id=PROVIDER_ID,
        )
        with self.assertRaises(CCConflictException):
            self.client.begin_transition(
                COMPACT,
                APPLICATION_ID,
                expected_version=int(seen.application['version']),
                expected_state_name=StateName.STARTED,
                pending_action=_pending('req-3'),
            )

    def test_clear_pending_action_ignores_a_different_request_id(self):
        self._create()
        self._enter(StateName.STARTED)
        version = int(self._application()['version'])
        self.client.begin_transition(
            COMPACT,
            APPLICATION_ID,
            expected_version=version,
            expected_state_name=StateName.STARTED,
            pending_action=_pending('req-keep'),
        )
        self.assertFalse(self.client.clear_pending_action(COMPACT, APPLICATION_ID, 'req-other'))
        self.assertEqual('req-keep', self._application()['pendingAction']['requestId'])
        self.assertTrue(self.client.clear_pending_action(COMPACT, APPLICATION_ID, 'req-keep'))
        self.assertNotIn('pendingAction', self._application())

    def test_delivery_attempt_and_request_record(self):
        self._create()
        self._enter(StateName.STARTED)
        version = int(self._application()['version'])
        self.client.begin_transition(
            COMPACT,
            APPLICATION_ID,
            expected_version=version,
            expected_state_name=StateName.STARTED,
            pending_action=_pending('req-deliver', action='ADVANCE'),
        )
        recorded = self.client.record_delivery_attempt(COMPACT, APPLICATION_ID, 'req-deliver')
        self.assertEqual(1, int(recorded['pendingAction']['attempts']))

        stored = self.client.put_request_record(
            COMPACT,
            APPLICATION_ID,
            'req-deliver',
            action='ADVANCE',
            result={'status': StoredStatus.FIRST_REVIEW.value},
            ttl=1_800_000_000,
        )
        loaded = self.client.get_request_record(COMPACT, APPLICATION_ID, 'req-deliver')
        self.assertEqual(stored['sk'], loaded['sk'])
        self.assertEqual('ADVANCE', loaded['action'])
        self.assertEqual(StoredStatus.FIRST_REVIEW.value, loaded['result']['status'])
        with self.assertRaises(CCConflictException):
            self.client.put_request_record(
                COMPACT,
                APPLICATION_ID,
                'req-deliver',
                action='ADVANCE',
                ttl=1_800_000_000,
            )
        self.assertIsNone(self.client.get_request_record(COMPACT, APPLICATION_ID, 'missing'))

    def test_begin_transition_records_the_active_application_review(self):
        self._create()
        self._enter(StateName.STAFF_REVIEW)
        self.client.assign_reviewers(
            COMPACT,
            APPLICATION_ID,
            {'firstReviewerSub': FIRST},
            expected_version=int(self._application()['version']),
        )
        self._enter(StateName.FIRST_REVIEW)
        version = int(self._application()['version'])
        stored = self.client.begin_transition(
            COMPACT,
            APPLICATION_ID,
            expected_version=version,
            expected_state_name=StateName.FIRST_REVIEW,
            pending_action=_pending('req-review', action='APPROVE'),
            application_review_update={
                'role': ActorRole.FIRST_REVIEWER,
                'reviewerSelectedApplicationStatus': 'approved',
                'notesForApplicant': 'Ready',
            },
        )
        review = self.client.locate_active_review(stored, ActorRole.FIRST_REVIEWER)
        self.assertEqual('approved', review['reviewerSelectedApplicationStatus'])
        self.assertEqual('Ready', review['notesForApplicant'])
        self.assertIn('reviewCompletionDate', review)


def _pending(request_id: str, action: str = 'SUBMIT') -> dict:
    return {
        'requestId': request_id,
        'action': action,
        'actorSub': PROVIDER_ID,
        'expectedStateName': StateName.STARTED.value,
        'expectedVersion': 1,
        'attempts': 0,
    }
