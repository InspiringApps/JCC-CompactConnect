from cc_common.applicants.application_state import ActorRole, ReviewSectionStatus, SectionName, StateName
from common_lambdas.exceptions import CCConflictException
from moto import mock_aws

from tests.function.test_application_client_mutations import (
    APPLICATION_ID,
    COMPACT,
    FIRST,
    PROVIDER_ID,
    ApplicationTableCase,
    _pending,
)


@mock_aws
class TestApplicationClientRaces(ApplicationTableCase):
    """Inject a write between a mutation's read and its conditional write."""

    def test_patch_during_submit_rejects_the_stale_transition(self):
        self._create()
        self._enter(StateName.STARTED)
        version = int(self._application()['version'])
        dynamodb = self.client.config.dynamodb_client
        real_update = dynamodb.update_item

        def wrapped(**kwargs):
            expression = kwargs.get('UpdateExpression', '')
            if not getattr(wrapped, 'injected', False) and 'pendingAction = :pendingAction' in expression:
                wrapped.injected = True
                dynamodb.update_item = real_update
                self.client.patch_section(
                    COMPACT,
                    APPLICATION_ID,
                    SectionName.PERSONAL_INFORMATION,
                    {'givenName': 'Ada'},
                    actor_provider_id=PROVIDER_ID,
                )
            return real_update(**kwargs)

        dynamodb.update_item = wrapped
        try:
            with self.assertRaises(CCConflictException):
                self.client.begin_transition(
                    COMPACT,
                    APPLICATION_ID,
                    expected_version=version,
                    expected_state_name=StateName.STARTED,
                    pending_action=_pending('req-submit'),
                )
        finally:
            dynamodb.update_item = real_update

        application = self._application()
        self.assertNotIn('pendingAction', application)
        section = self.client.get_snapshot(COMPACT, APPLICATION_ID).sections[SectionName.PERSONAL_INFORMATION]
        self.assertEqual('Ada', section['data']['givenName'])

    def test_reassignment_during_review_rejects_the_stale_review(self):
        self._create()
        self._enter(StateName.STAFF_REVIEW)
        assigned = self.client.assign_reviewers(
            COMPACT,
            APPLICATION_ID,
            {'firstReviewerSub': FIRST},
            expected_version=int(self._application()['version']),
        )
        self._enter(StateName.FIRST_REVIEW)
        version = int(self._application()['version'])
        dynamodb = self.client.config.dynamodb_client
        real_transact = dynamodb.transact_write_items

        def wrapped(**kwargs):
            section_update = kwargs['TransactItems'][0]['Update']['UpdateExpression']
            if not getattr(wrapped, 'injected', False) and 'reviewerSelectedApplicationSectionStatus' in section_update:
                wrapped.injected = True
                dynamodb.transact_write_items = real_transact
                self.client.assign_reviewers(
                    COMPACT,
                    APPLICATION_ID,
                    {'firstReviewerSub': 'reviewer-new'},
                    expected_version=version,
                )
            return real_transact(**kwargs)

        dynamodb.transact_write_items = wrapped
        try:
            with self.assertRaises(CCConflictException):
                self.client.save_section_review(
                    COMPACT,
                    APPLICATION_ID,
                    SectionName.PERSONAL_INFORMATION,
                    ActorRole.FIRST_REVIEWER,
                    FIRST,
                    ReviewSectionStatus.APPROVED,
                )
        finally:
            dynamodb.transact_write_items = real_transact

        snapshot = self.client.get_snapshot(COMPACT, APPLICATION_ID)
        reviews = snapshot.sections[SectionName.PERSONAL_INFORMATION]['reviews']
        self.assertEqual(
            assigned.snapshot.application['assignedFirstReviewerMetadata']['assignmentId'],
            reviews[0]['assignmentId'],
        )
        self.assertEqual(ReviewSectionStatus.PENDING.value, reviews[0]['reviewerSelectedApplicationSectionStatus'])
        self.assertEqual('reviewer-new', snapshot.application['assignedFirstReviewerMetadata']['cognitoSub'])

    def test_transition_during_transition_lets_exactly_one_win(self):
        self._create()
        self._enter(StateName.STARTED)
        version = int(self._application()['version'])
        dynamodb = self.client.config.dynamodb_client
        real_update = dynamodb.update_item

        def wrapped(**kwargs):
            expression = kwargs.get('UpdateExpression', '')
            if not getattr(wrapped, 'injected', False) and 'pendingAction = :pendingAction' in expression:
                wrapped.injected = True
                dynamodb.update_item = real_update
                self.client.begin_transition(
                    COMPACT,
                    APPLICATION_ID,
                    expected_version=version,
                    expected_state_name=StateName.STARTED,
                    pending_action=_pending('req-injected'),
                )
            return real_update(**kwargs)

        dynamodb.update_item = wrapped
        try:
            with self.assertRaises(CCConflictException):
                self.client.begin_transition(
                    COMPACT,
                    APPLICATION_ID,
                    expected_version=version,
                    expected_state_name=StateName.STARTED,
                    pending_action=_pending('req-outer'),
                )
        finally:
            dynamodb.update_item = real_update

        self.assertEqual('req-injected', self._application()['pendingAction']['requestId'])
