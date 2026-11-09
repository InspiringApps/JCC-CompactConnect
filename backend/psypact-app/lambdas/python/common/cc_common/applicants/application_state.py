"""PSYPACT application workflow vocabulary and authorization.

The transition table is the source of truth for which actions a state allows.
Admin override and deactivation are universal actions and are not edges in the table.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from common_lambdas.exceptions import CCAccessDeniedException, CCInvalidRequestException

FIRST_AND_SECOND_REVIEWER_MUST_DIFFER = 'FIRST_AND_SECOND_REVIEWER_MUST_DIFFER'


class ApplicationType(StrEnum):
    APIT = 'apit'
    TAP = 'tap'


class ApplicationStatus(StrEnum):
    STARTED = 'started'
    STAFF_REVIEW = 'staff-review'
    FIRST_REVIEW = 'first-review'
    SECOND_REVIEW = 'second-review'
    FINAL_REVIEW = 'final-review'
    COMMITTEE_REVIEW = 'committee-review'
    AWAITING_APPLICANT = 'awaiting-applicant'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    DEACTIVATED = 'deactivated'
    INTERNAL_ERROR = 'internal-error'


class ApplicantSectionStatus(StrEnum):
    INCOMPLETE = 'incomplete'
    COMPLETE = 'complete'
    NEEDS_ATTENTION = 'needs-attention'
    CONFIRM_DETAILS = 'confirm-details'


class ReviewSectionStatus(StrEnum):
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class ReviewerType(StrEnum):
    FIRST_REVIEWER = 'first-reviewer'
    SECOND_REVIEWER = 'second-reviewer'
    FINAL_REVIEWER = 'final-reviewer'


class ApplicationLicenseStatus(StrEnum):
    ACTIVE = 'active'
    INACTIVE = 'inactive'


class ReviewComparisonStatus(StrEnum):
    BOTH_APPROVE = 'both-approve'
    REVIEWERS_DIFFER = 'reviewers-differ'


class SectionName(StrEnum):
    PERSONAL_INFORMATION = 'personalInformation'
    LICENSE_HISTORY = 'licenseHistory'
    EDUCATION = 'education'
    CONDUCT_HISTORY = 'conductHistory'
    HOME_STATE = 'homeState'
    ACKNOWLEDGEMENTS = 'acknowledgements'


class ActorRole(StrEnum):
    APPLICANT = 'applicant'
    COMPACT_ADMIN = 'compact-admin'
    FIRST_REVIEWER = 'first-reviewer'
    SECOND_REVIEWER = 'second-reviewer'
    FINAL_REVIEWER = 'final-reviewer'


class WorkflowAction(StrEnum):
    SUBMIT = 'SUBMIT'
    REVIEWERS_ASSIGNED = 'REVIEWERS_ASSIGNED'
    ADVANCE = 'ADVANCE'
    SEND_TO_COMMITTEE = 'SEND_TO_COMMITTEE'
    REQUEST_CHANGES = 'REQUEST_CHANGES'
    RETURN_TO_REVIEW = 'RETURN_TO_REVIEW'
    RESUBMIT = 'RESUBMIT'
    APPROVE = 'APPROVE'
    REJECT = 'REJECT'
    ADMIN_OVERRIDE = 'ADMIN_OVERRIDE'
    ADMIN_DEACTIVATE = 'ADMIN_DEACTIVATE'


class StateName(StrEnum):
    STARTED = 'Started'
    STAFF_REVIEW = 'StaffReview'
    FIRST_REVIEW = 'FirstReview'
    SECOND_REVIEW = 'SecondReview'
    FINAL_REVIEW = 'FinalReview'
    COMMITTEE_FROM_FIRST = 'CommitteeFromFirst'
    COMMITTEE_FROM_SECOND = 'CommitteeFromSecond'
    COMMITTEE_FROM_FINAL = 'CommitteeFromFinal'
    AWAITING_APPLICANT_FROM_FIRST = 'AwaitingApplicantFromFirst'
    AWAITING_APPLICANT_FROM_SECOND = 'AwaitingApplicantFromSecond'
    AWAITING_APPLICANT_FROM_FINAL = 'AwaitingApplicantFromFinal'
    APPROVED = 'Approved'
    REJECTED = 'Rejected'
    DEACTIVATED = 'Deactivated'
    INTERNAL_ERROR = 'InternalError'


REVIEWER_ROLES = frozenset(
    {
        ActorRole.FIRST_REVIEWER,
        ActorRole.SECOND_REVIEWER,
        ActorRole.FINAL_REVIEWER,
    }
)

ADMIN_ACTIONS = frozenset({WorkflowAction.ADMIN_OVERRIDE, WorkflowAction.ADMIN_DEACTIVATE})


@dataclass(frozen=True, slots=True)
class StateDefinition:
    state_name: StateName
    status: ApplicationStatus
    actor_role: ActorRole | None
    terminal: bool
    transitions: Mapping[WorkflowAction, StateName]


def _transitions(**edges: StateName) -> Mapping[WorkflowAction, StateName]:
    return MappingProxyType({WorkflowAction[name]: target for name, target in edges.items()})


def _state(
    state_name: StateName,
    status: ApplicationStatus,
    actor_role: ActorRole | None,
    *,
    terminal: bool = False,
    transitions: Mapping[WorkflowAction, StateName] | None = None,
) -> StateDefinition:
    return StateDefinition(
        state_name=state_name,
        status=status,
        actor_role=actor_role,
        terminal=terminal,
        transitions=transitions if transitions is not None else MappingProxyType({}),
    )


STATE_DEFINITIONS: Mapping[StateName, StateDefinition] = MappingProxyType(
    {
        StateName.STARTED: _state(
            StateName.STARTED,
            ApplicationStatus.STARTED,
            ActorRole.APPLICANT,
            transitions=_transitions(SUBMIT=StateName.STAFF_REVIEW),
        ),
        StateName.STAFF_REVIEW: _state(
            StateName.STAFF_REVIEW,
            ApplicationStatus.STAFF_REVIEW,
            ActorRole.COMPACT_ADMIN,
            transitions=_transitions(REVIEWERS_ASSIGNED=StateName.FIRST_REVIEW),
        ),
        StateName.FIRST_REVIEW: _state(
            StateName.FIRST_REVIEW,
            ApplicationStatus.FIRST_REVIEW,
            ActorRole.FIRST_REVIEWER,
            transitions=_transitions(
                ADVANCE=StateName.SECOND_REVIEW,
                SEND_TO_COMMITTEE=StateName.COMMITTEE_FROM_FIRST,
                REQUEST_CHANGES=StateName.AWAITING_APPLICANT_FROM_FIRST,
            ),
        ),
        StateName.COMMITTEE_FROM_FIRST: _state(
            StateName.COMMITTEE_FROM_FIRST,
            ApplicationStatus.COMMITTEE_REVIEW,
            ActorRole.FIRST_REVIEWER,
            transitions=_transitions(
                RETURN_TO_REVIEW=StateName.FIRST_REVIEW,
                ADVANCE=StateName.SECOND_REVIEW,
                REQUEST_CHANGES=StateName.AWAITING_APPLICANT_FROM_FIRST,
            ),
        ),
        StateName.AWAITING_APPLICANT_FROM_FIRST: _state(
            StateName.AWAITING_APPLICANT_FROM_FIRST,
            ApplicationStatus.AWAITING_APPLICANT,
            ActorRole.APPLICANT,
            transitions=_transitions(RESUBMIT=StateName.FIRST_REVIEW),
        ),
        StateName.SECOND_REVIEW: _state(
            StateName.SECOND_REVIEW,
            ApplicationStatus.SECOND_REVIEW,
            ActorRole.SECOND_REVIEWER,
            transitions=_transitions(
                ADVANCE=StateName.FINAL_REVIEW,
                SEND_TO_COMMITTEE=StateName.COMMITTEE_FROM_SECOND,
                REQUEST_CHANGES=StateName.AWAITING_APPLICANT_FROM_SECOND,
            ),
        ),
        StateName.COMMITTEE_FROM_SECOND: _state(
            StateName.COMMITTEE_FROM_SECOND,
            ApplicationStatus.COMMITTEE_REVIEW,
            ActorRole.SECOND_REVIEWER,
            transitions=_transitions(
                RETURN_TO_REVIEW=StateName.SECOND_REVIEW,
                ADVANCE=StateName.FINAL_REVIEW,
                REQUEST_CHANGES=StateName.AWAITING_APPLICANT_FROM_SECOND,
            ),
        ),
        StateName.AWAITING_APPLICANT_FROM_SECOND: _state(
            StateName.AWAITING_APPLICANT_FROM_SECOND,
            ApplicationStatus.AWAITING_APPLICANT,
            ActorRole.APPLICANT,
            transitions=_transitions(RESUBMIT=StateName.SECOND_REVIEW),
        ),
        StateName.FINAL_REVIEW: _state(
            StateName.FINAL_REVIEW,
            ApplicationStatus.FINAL_REVIEW,
            ActorRole.FINAL_REVIEWER,
            transitions=_transitions(
                APPROVE=StateName.APPROVED,
                REJECT=StateName.REJECTED,
                SEND_TO_COMMITTEE=StateName.COMMITTEE_FROM_FINAL,
                REQUEST_CHANGES=StateName.AWAITING_APPLICANT_FROM_FINAL,
            ),
        ),
        StateName.COMMITTEE_FROM_FINAL: _state(
            StateName.COMMITTEE_FROM_FINAL,
            ApplicationStatus.COMMITTEE_REVIEW,
            ActorRole.FINAL_REVIEWER,
            transitions=_transitions(
                RETURN_TO_REVIEW=StateName.FINAL_REVIEW,
                APPROVE=StateName.APPROVED,
                REJECT=StateName.REJECTED,
                REQUEST_CHANGES=StateName.AWAITING_APPLICANT_FROM_FINAL,
            ),
        ),
        StateName.AWAITING_APPLICANT_FROM_FINAL: _state(
            StateName.AWAITING_APPLICANT_FROM_FINAL,
            ApplicationStatus.AWAITING_APPLICANT,
            ActorRole.APPLICANT,
            transitions=_transitions(RESUBMIT=StateName.FINAL_REVIEW),
        ),
        StateName.APPROVED: _state(StateName.APPROVED, ApplicationStatus.APPROVED, None, terminal=True),
        StateName.REJECTED: _state(StateName.REJECTED, ApplicationStatus.REJECTED, None, terminal=True),
        StateName.DEACTIVATED: _state(StateName.DEACTIVATED, ApplicationStatus.DEACTIVATED, None, terminal=True),
        StateName.INTERNAL_ERROR: _state(
            StateName.INTERNAL_ERROR, ApplicationStatus.INTERNAL_ERROR, None, terminal=True
        ),
    }
)


WAIT_STATES = frozenset(state for state, definition in STATE_DEFINITIONS.items() if not definition.terminal)
ADMIN_OVERRIDE_TARGETS = frozenset(state for state in StateName if state is not StateName.INTERNAL_ERROR)
ACTIONS_REQUIRING_COMPLETE_REVIEWS = frozenset({WorkflowAction.ADVANCE, WorkflowAction.APPROVE, WorkflowAction.REJECT})
APPLICANT_EDITABLE_STATES = frozenset(
    {
        StateName.STARTED,
        StateName.AWAITING_APPLICANT_FROM_FIRST,
        StateName.AWAITING_APPLICANT_FROM_SECOND,
        StateName.AWAITING_APPLICANT_FROM_FINAL,
    }
)

_REVIEWER_EDIT_STATES = MappingProxyType(
    {
        ActorRole.FIRST_REVIEWER: (StateName.FIRST_REVIEW, StateName.COMMITTEE_FROM_FIRST),
        ActorRole.SECOND_REVIEWER: (StateName.SECOND_REVIEW, StateName.COMMITTEE_FROM_SECOND),
        ActorRole.FINAL_REVIEWER: (StateName.FINAL_REVIEW, StateName.COMMITTEE_FROM_FINAL),
    }
)


def is_terminal(state: StateName) -> bool:
    return STATE_DEFINITIONS[state].terminal


def reviewer_edit_states(role: ActorRole) -> tuple[StateName, StateName]:
    """Return the review node and committee node where this reviewer may edit."""
    try:
        return _REVIEWER_EDIT_STATES[role]
    except KeyError as error:
        raise ValueError(f'{role} is not a reviewer role') from error


@dataclass(frozen=True, slots=True)
class Caller:
    sub: str
    scopes: set[str]
    provider_id: str | None = None


@dataclass(frozen=True, slots=True)
class ApplicationAuthContext:
    compact: str
    state_name: StateName
    provider_id: str | None
    first_reviewer_sub: str | None = None
    second_reviewer_sub: str | None = None
    final_reviewer_sub: str | None = None


def _compact_admin_scope(compact: str) -> str:
    return f'{compact}/admin'


def _is_compact_admin(caller: Caller, compact: str) -> bool:
    return _compact_admin_scope(compact) in caller.scopes


def _assigned_reviewer_sub(ctx: ApplicationAuthContext, role: ActorRole) -> str | None:
    if role is ActorRole.FIRST_REVIEWER:
        return ctx.first_reviewer_sub
    if role is ActorRole.SECOND_REVIEWER:
        return ctx.second_reviewer_sub
    if role is ActorRole.FINAL_REVIEWER:
        return ctx.final_reviewer_sub
    return None


def authorize_action(caller: Caller, ctx: ApplicationAuthContext, action: WorkflowAction, compact: str) -> None:
    """Allow the caller to take ``action`` in the application's current state.

    Raises CCInvalidRequestException when the action is not a legal edge.
    Raises CCAccessDeniedException when the caller is not the actor for that edge.
    Jurisdiction admin scopes do not grant any application permission.
    """
    definition = STATE_DEFINITIONS[ctx.state_name]

    if action in ADMIN_ACTIONS:
        if definition.terminal or not _is_compact_admin(caller, compact):
            raise CCAccessDeniedException('Forbidden access attempt!')
        return

    if action not in definition.transitions:
        raise CCInvalidRequestException(f'{action} is not allowed from {ctx.state_name}')

    actor_role = definition.actor_role
    if actor_role is ActorRole.APPLICANT:
        if caller.provider_id is None or caller.provider_id != ctx.provider_id:
            raise CCAccessDeniedException('Forbidden access attempt!')
        return

    if actor_role is ActorRole.COMPACT_ADMIN:
        if not _is_compact_admin(caller, compact):
            raise CCAccessDeniedException('Forbidden access attempt!')
        return

    if actor_role in REVIEWER_ROLES:
        assigned_sub = _assigned_reviewer_sub(ctx, actor_role)
        if not _is_compact_admin(caller, compact) or caller.sub != assigned_sub:
            raise CCAccessDeniedException('Forbidden access attempt!')
        return

    raise CCAccessDeniedException('Forbidden access attempt!')


def validate_reviewer_assignment(first: str | None, second: str | None, final: str | None) -> None:
    """Reject an assignment where the first and second reviewers are the same person.

    The final reviewer may be the same person as the first, the second, or both.
    """
    del final
    if first and second and first == second:
        raise CCInvalidRequestException(FIRST_AND_SECOND_REVIEWER_MUST_DIFFER)


def override_target_allowed(ctx: ApplicationAuthContext, target: StateName) -> bool:
    """Return whether an admin override may move the application to ``target``.

    A reviewer node requires that role to be assigned. First and second reviewers
    must still be different people whenever both are set. Internal error is not a target.
    """
    if target not in ADMIN_OVERRIDE_TARGETS:
        return False
    if ctx.first_reviewer_sub and ctx.second_reviewer_sub and ctx.first_reviewer_sub == ctx.second_reviewer_sub:
        return False

    actor_role = STATE_DEFINITIONS[target].actor_role
    if actor_role in REVIEWER_ROLES and not _assigned_reviewer_sub(ctx, actor_role):
        return False
    return True
