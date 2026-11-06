from unittest import TestCase

from cc_common.applicants.application_state import (
    ACTIONS_REQUIRING_COMPLETE_REVIEWS,
    ADMIN_OVERRIDE_TARGETS,
    APPLICANT_EDITABLE_STATES,
    FIRST_AND_SECOND_REVIEWER_MUST_DIFFER,
    STATE_DEFINITIONS,
    WAIT_STATES,
    ActorRole,
    ApplicationAuthContext,
    ApplicationStatus,
    Caller,
    StateName,
    WorkflowAction,
    authorize_action,
    is_terminal,
    override_target_allowed,
    reviewer_edit_states,
    validate_reviewer_assignment,
)
from common_lambdas.exceptions import CCAccessDeniedException, CCInvalidRequestException

COMPACT = 'psy'
APPLICANT_ID = 'provider-1'
FIRST = 'first-sub'
SECOND = 'second-sub'
FINAL = 'final-sub'
COMPACT_ADMIN = f'{COMPACT}/admin'
JURISDICTION_ADMIN = f'oh/{COMPACT}.admin'

EXPECTED_TRANSITIONS = {
    StateName.STARTED: {WorkflowAction.SUBMIT: StateName.STAFF_REVIEW},
    StateName.STAFF_REVIEW: {WorkflowAction.REVIEWERS_ASSIGNED: StateName.FIRST_REVIEW},
    StateName.FIRST_REVIEW: {
        WorkflowAction.ADVANCE: StateName.SECOND_REVIEW,
        WorkflowAction.SEND_TO_COMMITTEE: StateName.COMMITTEE_FROM_FIRST,
        WorkflowAction.REQUEST_CHANGES: StateName.AWAITING_APPLICANT_FROM_FIRST,
    },
    StateName.COMMITTEE_FROM_FIRST: {
        WorkflowAction.RETURN_TO_REVIEW: StateName.FIRST_REVIEW,
        WorkflowAction.ADVANCE: StateName.SECOND_REVIEW,
        WorkflowAction.REQUEST_CHANGES: StateName.AWAITING_APPLICANT_FROM_FIRST,
    },
    StateName.AWAITING_APPLICANT_FROM_FIRST: {WorkflowAction.RESUBMIT: StateName.FIRST_REVIEW},
    StateName.SECOND_REVIEW: {
        WorkflowAction.ADVANCE: StateName.FINAL_REVIEW,
        WorkflowAction.SEND_TO_COMMITTEE: StateName.COMMITTEE_FROM_SECOND,
        WorkflowAction.REQUEST_CHANGES: StateName.AWAITING_APPLICANT_FROM_SECOND,
    },
    StateName.COMMITTEE_FROM_SECOND: {
        WorkflowAction.RETURN_TO_REVIEW: StateName.SECOND_REVIEW,
        WorkflowAction.ADVANCE: StateName.FINAL_REVIEW,
        WorkflowAction.REQUEST_CHANGES: StateName.AWAITING_APPLICANT_FROM_SECOND,
    },
    StateName.AWAITING_APPLICANT_FROM_SECOND: {WorkflowAction.RESUBMIT: StateName.SECOND_REVIEW},
    StateName.FINAL_REVIEW: {
        WorkflowAction.APPROVE: StateName.APPROVED,
        WorkflowAction.REJECT: StateName.REJECTED,
        WorkflowAction.SEND_TO_COMMITTEE: StateName.COMMITTEE_FROM_FINAL,
        WorkflowAction.REQUEST_CHANGES: StateName.AWAITING_APPLICANT_FROM_FINAL,
    },
    StateName.COMMITTEE_FROM_FINAL: {
        WorkflowAction.RETURN_TO_REVIEW: StateName.FINAL_REVIEW,
        WorkflowAction.APPROVE: StateName.APPROVED,
        WorkflowAction.REJECT: StateName.REJECTED,
        WorkflowAction.REQUEST_CHANGES: StateName.AWAITING_APPLICANT_FROM_FINAL,
    },
    StateName.AWAITING_APPLICANT_FROM_FINAL: {WorkflowAction.RESUBMIT: StateName.FINAL_REVIEW},
    StateName.APPROVED: {},
    StateName.REJECTED: {},
    StateName.DEACTIVATED: {},
}

EXPECTED_ACTORS = {
    StateName.STARTED: ActorRole.APPLICANT,
    StateName.STAFF_REVIEW: ActorRole.COMPACT_ADMIN,
    StateName.FIRST_REVIEW: ActorRole.FIRST_REVIEWER,
    StateName.COMMITTEE_FROM_FIRST: ActorRole.FIRST_REVIEWER,
    StateName.AWAITING_APPLICANT_FROM_FIRST: ActorRole.APPLICANT,
    StateName.SECOND_REVIEW: ActorRole.SECOND_REVIEWER,
    StateName.COMMITTEE_FROM_SECOND: ActorRole.SECOND_REVIEWER,
    StateName.AWAITING_APPLICANT_FROM_SECOND: ActorRole.APPLICANT,
    StateName.FINAL_REVIEW: ActorRole.FINAL_REVIEWER,
    StateName.COMMITTEE_FROM_FINAL: ActorRole.FINAL_REVIEWER,
    StateName.AWAITING_APPLICANT_FROM_FINAL: ActorRole.APPLICANT,
    StateName.APPROVED: None,
    StateName.REJECTED: None,
    StateName.DEACTIVATED: None,
}

EXPECTED_STATUS = {
    StateName.STARTED: ApplicationStatus.STARTED,
    StateName.STAFF_REVIEW: ApplicationStatus.STAFF_REVIEW,
    StateName.FIRST_REVIEW: ApplicationStatus.FIRST_REVIEW,
    StateName.SECOND_REVIEW: ApplicationStatus.SECOND_REVIEW,
    StateName.FINAL_REVIEW: ApplicationStatus.FINAL_REVIEW,
    StateName.COMMITTEE_FROM_FIRST: ApplicationStatus.COMMITTEE_REVIEW,
    StateName.COMMITTEE_FROM_SECOND: ApplicationStatus.COMMITTEE_REVIEW,
    StateName.COMMITTEE_FROM_FINAL: ApplicationStatus.COMMITTEE_REVIEW,
    StateName.AWAITING_APPLICANT_FROM_FIRST: ApplicationStatus.AWAITING_APPLICANT,
    StateName.AWAITING_APPLICANT_FROM_SECOND: ApplicationStatus.AWAITING_APPLICANT,
    StateName.AWAITING_APPLICANT_FROM_FINAL: ApplicationStatus.AWAITING_APPLICANT,
    StateName.APPROVED: ApplicationStatus.APPROVED,
    StateName.REJECTED: ApplicationStatus.REJECTED,
    StateName.DEACTIVATED: ApplicationStatus.DEACTIVATED,
}


def _context(state: StateName, **overrides) -> ApplicationAuthContext:
    values = {
        'compact': COMPACT,
        'state_name': state,
        'provider_id': APPLICANT_ID,
        'first_reviewer_sub': FIRST,
        'second_reviewer_sub': SECOND,
        'final_reviewer_sub': FINAL,
    }
    values.update(overrides)
    return ApplicationAuthContext(**values)


class TestStateDefinitions(TestCase):
    def test_edges_match_exactly(self):
        self.assertEqual(set(STATE_DEFINITIONS), set(StateName))
        for state, expected in EXPECTED_TRANSITIONS.items():
            definition = STATE_DEFINITIONS[state]
            self.assertEqual(dict(definition.transitions), expected)
            self.assertEqual(definition.actor_role, EXPECTED_ACTORS[state])
            self.assertEqual(definition.status, EXPECTED_STATUS[state])
            self.assertEqual(definition.terminal, not expected)
            self.assertEqual(is_terminal(state), not expected)

    def test_admin_actions_are_not_table_edges(self):
        for definition in STATE_DEFINITIONS.values():
            admin_actions = {WorkflowAction.ADMIN_OVERRIDE, WorkflowAction.ADMIN_DEACTIVATE}
            self.assertTrue(set(definition.transitions).isdisjoint(admin_actions))

    def test_non_terminal_states_are_reachable_from_started(self):
        reachable = set()
        pending = [StateName.STARTED]
        while pending:
            state = pending.pop()
            if state in reachable:
                continue
            reachable.add(state)
            pending.extend(STATE_DEFINITIONS[state].transitions.values())

        self.assertEqual(reachable - {StateName.APPROVED, StateName.REJECTED}, WAIT_STATES)
        self.assertTrue({StateName.APPROVED, StateName.REJECTED} <= reachable)
        self.assertNotIn(StateName.DEACTIVATED, reachable)

    def test_terminal_states_have_no_transitions(self):
        for state in (StateName.APPROVED, StateName.REJECTED, StateName.DEACTIVATED):
            self.assertEqual(dict(STATE_DEFINITIONS[state].transitions), {})
            self.assertTrue(is_terminal(state))
            self.assertNotIn(state, WAIT_STATES)

    def test_constants(self):
        self.assertEqual(ADMIN_OVERRIDE_TARGETS, frozenset(StateName))
        self.assertEqual(
            ACTIONS_REQUIRING_COMPLETE_REVIEWS,
            frozenset({WorkflowAction.ADVANCE, WorkflowAction.APPROVE, WorkflowAction.REJECT}),
        )
        self.assertEqual(
            APPLICANT_EDITABLE_STATES,
            frozenset(
                {
                    StateName.STARTED,
                    StateName.AWAITING_APPLICANT_FROM_FIRST,
                    StateName.AWAITING_APPLICANT_FROM_SECOND,
                    StateName.AWAITING_APPLICANT_FROM_FINAL,
                }
            ),
        )
        self.assertEqual(
            reviewer_edit_states(ActorRole.FIRST_REVIEWER),
            (StateName.FIRST_REVIEW, StateName.COMMITTEE_FROM_FIRST),
        )
        self.assertEqual(
            reviewer_edit_states(ActorRole.SECOND_REVIEWER),
            (StateName.SECOND_REVIEW, StateName.COMMITTEE_FROM_SECOND),
        )
        self.assertEqual(
            reviewer_edit_states(ActorRole.FINAL_REVIEWER),
            (StateName.FINAL_REVIEW, StateName.COMMITTEE_FROM_FINAL),
        )
        with self.assertRaises(ValueError):
            reviewer_edit_states(ActorRole.APPLICANT)


class TestAuthorizeAction(TestCase):
    def test_applicant_can_submit_and_resubmit_only_as_owner(self):
        applicant = Caller(sub='user', scopes=set(), provider_id=APPLICANT_ID)
        other = Caller(sub='user', scopes={COMPACT_ADMIN}, provider_id='someone-else')

        authorize_action(applicant, _context(StateName.STARTED), WorkflowAction.SUBMIT, COMPACT)
        authorize_action(
            applicant,
            _context(StateName.AWAITING_APPLICANT_FROM_SECOND),
            WorkflowAction.RESUBMIT,
            COMPACT,
        )
        with self.assertRaises(CCAccessDeniedException):
            authorize_action(other, _context(StateName.STARTED), WorkflowAction.SUBMIT, COMPACT)

    def test_each_reviewer_role_requires_matching_sub_and_compact_admin(self):
        cases = (
            (StateName.FIRST_REVIEW, FIRST, WorkflowAction.ADVANCE),
            (StateName.COMMITTEE_FROM_FIRST, FIRST, WorkflowAction.RETURN_TO_REVIEW),
            (StateName.SECOND_REVIEW, SECOND, WorkflowAction.SEND_TO_COMMITTEE),
            (StateName.COMMITTEE_FROM_SECOND, SECOND, WorkflowAction.REQUEST_CHANGES),
            (StateName.FINAL_REVIEW, FINAL, WorkflowAction.APPROVE),
            (StateName.COMMITTEE_FROM_FINAL, FINAL, WorkflowAction.REJECT),
        )
        for state, sub, action in cases:
            with self.subTest(state=state, action=action):
                authorize_action(Caller(sub=sub, scopes={COMPACT_ADMIN}), _context(state), action, COMPACT)
                with self.assertRaises(CCAccessDeniedException):
                    authorize_action(Caller(sub='other-sub', scopes={COMPACT_ADMIN}), _context(state), action, COMPACT)
                with self.assertRaises(CCAccessDeniedException):
                    authorize_action(Caller(sub=sub, scopes={JURISDICTION_ADMIN}), _context(state), action, COMPACT)

    def test_committee_access_is_limited_to_the_sending_role(self):
        authorize_action(
            Caller(sub=FIRST, scopes={COMPACT_ADMIN}),
            _context(StateName.COMMITTEE_FROM_FIRST),
            WorkflowAction.ADVANCE,
            COMPACT,
        )
        for wrong_sub in (SECOND, FINAL):
            with self.assertRaises(CCAccessDeniedException):
                authorize_action(
                    Caller(sub=wrong_sub, scopes={COMPACT_ADMIN}),
                    _context(StateName.COMMITTEE_FROM_FIRST),
                    WorkflowAction.ADVANCE,
                    COMPACT,
                )

    def test_staff_review_requires_compact_admin(self):
        authorize_action(
            Caller(sub='admin', scopes={COMPACT_ADMIN}),
            _context(StateName.STAFF_REVIEW),
            WorkflowAction.REVIEWERS_ASSIGNED,
            COMPACT,
        )
        with self.assertRaises(CCAccessDeniedException):
            authorize_action(
                Caller(sub=FIRST, scopes={JURISDICTION_ADMIN}, provider_id=APPLICANT_ID),
                _context(StateName.STAFF_REVIEW),
                WorkflowAction.REVIEWERS_ASSIGNED,
                COMPACT,
            )

    def test_compact_admin_override_is_allowed_only_in_non_terminal_states(self):
        admin = Caller(sub='admin', scopes={COMPACT_ADMIN})
        for state in WAIT_STATES:
            with self.subTest(state=state):
                authorize_action(admin, _context(state), WorkflowAction.ADMIN_OVERRIDE, COMPACT)
                authorize_action(admin, _context(state), WorkflowAction.ADMIN_DEACTIVATE, COMPACT)

        for state in (StateName.APPROVED, StateName.REJECTED, StateName.DEACTIVATED):
            with self.subTest(state=state), self.assertRaises(CCAccessDeniedException):
                authorize_action(admin, _context(state), WorkflowAction.ADMIN_OVERRIDE, COMPACT)

    def test_jurisdiction_admin_scope_grants_nothing(self):
        caller = Caller(sub=FIRST, scopes={JURISDICTION_ADMIN}, provider_id='not-the-applicant')
        staff_actions = (
            (StateName.STARTED, WorkflowAction.ADMIN_OVERRIDE),
            (StateName.STAFF_REVIEW, WorkflowAction.REVIEWERS_ASSIGNED),
            (StateName.FIRST_REVIEW, WorkflowAction.ADVANCE),
            (StateName.FINAL_REVIEW, WorkflowAction.ADMIN_DEACTIVATE),
        )
        for state, action in staff_actions:
            with self.subTest(state=state, action=action), self.assertRaises(CCAccessDeniedException):
                authorize_action(caller, _context(state), action, COMPACT)

    def test_illegal_action_is_an_invalid_request(self):
        applicant = Caller(sub='user', scopes=set(), provider_id=APPLICANT_ID)
        with self.assertRaises(CCInvalidRequestException):
            authorize_action(applicant, _context(StateName.STARTED), WorkflowAction.APPROVE, COMPACT)
        with self.assertRaises(CCInvalidRequestException):
            authorize_action(
                Caller(sub=FIRST, scopes={COMPACT_ADMIN}),
                _context(StateName.FIRST_REVIEW),
                WorkflowAction.RESUBMIT,
                COMPACT,
            )


class TestReviewerAssignment(TestCase):
    def test_distinctness_combinations(self):
        allowed = (
            (FIRST, SECOND, None),
            (FIRST, SECOND, FIRST),
            (FIRST, SECOND, SECOND),
            (FIRST, SECOND, FIRST),
            (FIRST, None, FIRST),
            (None, SECOND, SECOND),
            (None, None, None),
            (FIRST, SECOND, 'both-as-final'),
        )
        # Final equal to both means first and second are the same person, which is rejected.
        validate_reviewer_assignment(FIRST, SECOND, FIRST)
        validate_reviewer_assignment(FIRST, SECOND, SECOND)
        validate_reviewer_assignment(None, None, FINAL)
        validate_reviewer_assignment(FIRST, None, FIRST)
        validate_reviewer_assignment(None, SECOND, SECOND)

        with self.assertRaises(CCInvalidRequestException) as raised:
            validate_reviewer_assignment(FIRST, FIRST, FINAL)
        self.assertEqual(FIRST_AND_SECOND_REVIEWER_MUST_DIFFER, raised.exception.message)

        with self.assertRaises(CCInvalidRequestException) as same_person:
            validate_reviewer_assignment(FIRST, FIRST, FIRST)
        self.assertEqual(FIRST_AND_SECOND_REVIEWER_MUST_DIFFER, same_person.exception.message)

        for first, second, final in allowed:
            if first and second and first == second:
                continue
            validate_reviewer_assignment(first, second, final)

    def test_override_requires_assigned_reviewer_and_distinct_first_and_second(self):
        ready = _context(StateName.STAFF_REVIEW)
        self.assertTrue(override_target_allowed(ready, StateName.SECOND_REVIEW))
        self.assertTrue(override_target_allowed(ready, StateName.APPROVED))

        missing_second = _context(StateName.FIRST_REVIEW, second_reviewer_sub=None)
        self.assertFalse(override_target_allowed(missing_second, StateName.SECOND_REVIEW))
        self.assertFalse(override_target_allowed(missing_second, StateName.COMMITTEE_FROM_SECOND))
        self.assertTrue(override_target_allowed(missing_second, StateName.FIRST_REVIEW))
        self.assertTrue(override_target_allowed(missing_second, StateName.STAFF_REVIEW))

        same_reviewers = _context(StateName.STAFF_REVIEW, second_reviewer_sub=FIRST)
        self.assertFalse(override_target_allowed(same_reviewers, StateName.APPROVED))
        self.assertFalse(override_target_allowed(same_reviewers, StateName.FIRST_REVIEW))
