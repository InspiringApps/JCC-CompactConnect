"""Validate an application transition and deliver it to Step Functions."""

import time
from collections.abc import Mapping
from dataclasses import dataclass

from aws_lambda_powertools.metrics import MetricUnit
from botocore.exceptions import BotoCoreError, ClientError
from common_lambdas.exceptions import CCConflictException, CCInvalidRequestException, CCNotFoundException

from cc_common.applicants.application_client import APPLICATION_TRANSITION_RECORD_TYPE
from cc_common.applicants.application_state import (
    ACTIONS_REQUIRING_COMPLETE_REVIEWS,
    REVIEWER_ROLES,
    STATE_DEFINITIONS,
    ApplicationAuthContext,
    StateName,
    WorkflowAction,
    authorize_action,
    override_target_allowed,
    validate_reviewer_assignment,
)
from cc_common.applicants.application_workflow_client import (
    CallbackDelivery,
    WorkflowStartAmbiguous,
    inputs_match,
)
from cc_common.config import logger, metrics

_MAX_DELIVERY_ATTEMPTS = 3
_POLL_TIMEOUT_SECONDS = 5
_POLL_INTERVAL_SECONDS = 0.2
_BACKOFF_SECONDS = 0.05
_REQUEST_TTL_SECONDS = 365 * 24 * 60 * 60
_STATES_REQUIRING_DISTINCT_REVIEWERS = frozenset({StateName.FIRST_REVIEW, StateName.STAFF_REVIEW})


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """The outcome an API handler returns for one transition request."""

    application_id: str
    request_id: str
    pending: bool
    accepted: bool
    status: str | None = None
    expected_status: str | None = None
    state_name: str | None = None
    generation: int | None = None

    def as_dict(self) -> dict:
        stored = {
            'applicationId': self.application_id,
            'requestId': self.request_id,
            'pending': self.pending,
            'accepted': self.accepted,
        }
        if self.status is not None:
            stored['status'] = self.status
        if self.expected_status is not None:
            stored['expectedStatus'] = self.expected_status
        if self.state_name is not None:
            stored['stateName'] = self.state_name
        if self.generation is not None:
            stored['generation'] = self.generation
        return stored


class ApplicationTransitionService:
    """Claim a transition in DynamoDB, then deliver the callback within a fixed bound."""

    def __init__(
        self,
        config,
        *,
        workflow_client=None,
        schedule_creator=None,
        sleeper=None,
        poll_timeout_seconds: float = _POLL_TIMEOUT_SECONDS,
        backoff_seconds: float = _BACKOFF_SECONDS,
    ):
        self.config = config
        self.applications = config.application_client
        self.workflow = workflow_client if workflow_client is not None else config.application_workflow_client
        self._schedule_creator = schedule_creator if schedule_creator is not None else _noop_schedule
        self._sleep = sleeper if sleeper is not None else time.sleep
        self._poll_timeout = poll_timeout_seconds
        self._backoff = backoff_seconds

    def submit_or_transition(
        self,
        compact: str,
        application_id: str,
        caller,
        action: WorkflowAction | str,
        request_id: str,
        *,
        notes_for_applicant: str | None = None,
        notes_for_reviewers: str | None = None,
        reviewer_selected_application_status: str | None = None,
    ) -> TransitionResult:
        """Authorize one table action, claim it, and deliver the callback."""
        return self._perform(
            compact,
            application_id,
            caller,
            WorkflowAction(action),
            request_id,
            target_state=None,
            notes_for_applicant=notes_for_applicant,
            notes_for_reviewers=notes_for_reviewers,
            reviewer_selected_application_status=reviewer_selected_application_status,
        )

    def admin_override(
        self,
        compact: str,
        application_id: str,
        caller,
        request_id: str,
        target_state: StateName | str,
        *,
        notes_for_applicant: str | None = None,
        notes_for_reviewers: str | None = None,
    ) -> TransitionResult:
        """Move a non-terminal application to ``target_state`` when that target is allowed."""
        return self._perform(
            compact,
            application_id,
            caller,
            WorkflowAction.ADMIN_OVERRIDE,
            request_id,
            target_state=StateName(target_state),
            notes_for_applicant=notes_for_applicant,
            notes_for_reviewers=notes_for_reviewers,
            reviewer_selected_application_status=None,
        )

    def admin_deactivate(self, compact: str, application_id: str, caller, request_id: str) -> TransitionResult:
        """Ask the running execution to deactivate the application."""
        return self._perform(
            compact,
            application_id,
            caller,
            WorkflowAction.ADMIN_DEACTIVATE,
            request_id,
            target_state=None,
            notes_for_applicant=None,
            notes_for_reviewers=None,
            reviewer_selected_application_status=None,
        )

    def deliver(self, application_item: Mapping, pending_action: Mapping) -> TransitionResult:
        """Send the stored callback, retrying only while the outcome stays unknown.

        A retryable or stale-token response is checked against the application and its
        transition audit before another attempt. An ambiguous failure never clears
        ``pendingAction``.
        """
        compact = str(application_item['compact'])
        application_id = str(application_item['applicationId'])
        request_id = str(pending_action['requestId'])
        expected_status = _expected_status(pending_action)
        current = dict(application_item)

        for attempt in range(1, _MAX_DELIVERY_ATTEMPTS + 1):
            try:
                current = self.applications.record_delivery_attempt(compact, application_id, request_id)
            except CCConflictException:
                advanced = self._completed_if_advanced(compact, application_id, pending_action, expected_status)
                if advanced is not None:
                    return advanced
                raise

            outcome = self._send_once(current)
            if outcome is CallbackDelivery.SUCCESS:
                return TransitionResult(
                    application_id=application_id,
                    request_id=request_id,
                    pending=True,
                    accepted=True,
                    status=current.get('status'),
                    expected_status=expected_status,
                    state_name=current.get('stateName'),
                    generation=_generation(current),
                )

            advanced = self._completed_if_advanced(compact, application_id, pending_action, expected_status)
            if advanced is not None:
                return advanced

            if outcome is CallbackDelivery.STALE and self._clear_if_not_running(current, request_id):
                latest = self._require_application(compact, application_id)
                return TransitionResult(
                    application_id=application_id,
                    request_id=request_id,
                    pending=False,
                    accepted=False,
                    status=latest.get('status'),
                    expected_status=expected_status,
                    state_name=latest.get('stateName'),
                    generation=_generation(latest),
                )

            if attempt < _MAX_DELIVERY_ATTEMPTS and self._should_retry(outcome, current):
                self._sleep(self._backoff * (2 ** (attempt - 1)))
                current = self._require_application(compact, application_id)
                continue
            break

        self._exhausted(application_id, request_id)
        latest = self._require_application(compact, application_id)
        return TransitionResult(
            application_id=application_id,
            request_id=request_id,
            pending=True,
            accepted=False,
            status=latest.get('status'),
            expected_status=expected_status,
            state_name=latest.get('stateName'),
            generation=_generation(latest),
        )

    def resume_delivery(self, compact: str, application_id: str, request_id: str) -> TransitionResult:
        """Continue the pending callback for ``request_id``. A different pending request conflicts."""
        application = self._require_application(compact, application_id)
        pending = application.get('pendingAction') or {}
        if pending.get('requestId') == request_id:
            return self._deliver_and_wait(application, pending)
        if pending:
            raise CCConflictException('A transition is already pending')
        stored = self._stored_result(compact, application_id, request_id)
        if stored is not None:
            return stored
        raise CCConflictException('No pending transition for this request')

    def create_application_and_start(
        self,
        compact: str,
        application_id: str,
        *,
        provider_id: str,
        types: list,
        is_renewal: bool,
        created: str,
        workflow_expires_at: str,
        start_at: StateName | str = StateName.STARTED,
        generation: int = 1,
    ) -> TransitionResult:
        """Create the application, create its expiry schedule, then start the execution.

        An ambiguous start is retried and then described. The application item is left in
        place unless this method has proved that no execution exists, and even then it is
        kept as a recoverable creation record.
        """
        start_state = StateName(start_at)
        execution_arn = self.workflow.execution_arn(compact, application_id, generation)
        schedule_name = self.workflow.execution_name(application_id, generation)
        self.applications.create_application(
            compact,
            application_id,
            execution_arn=execution_arn,
            schedule_name=schedule_name,
            workflow_expires_at=workflow_expires_at,
            provider_id=provider_id,
            types=types,
            is_renewal=is_renewal,
            created=created,
        )
        self._schedule_creator(
            compact=compact,
            application_id=application_id,
            generation=generation,
            schedule_name=schedule_name,
            workflow_expires_at=workflow_expires_at,
            execution_arn=execution_arn,
        )
        self._start_execution(
            compact=compact,
            application_id=application_id,
            generation=generation,
            workflow_expires_at=workflow_expires_at,
            start_at=start_state.value,
        )
        expected_status = STATE_DEFINITIONS[start_state].status.value
        return self._poll_for_status(compact, application_id, expected_status, generation)

    def _perform(
        self,
        compact: str,
        application_id: str,
        caller,
        action: WorkflowAction,
        request_id: str,
        *,
        target_state: StateName | None,
        notes_for_applicant: str | None,
        notes_for_reviewers: str | None,
        reviewer_selected_application_status: str | None,
    ) -> TransitionResult:
        stored = self._stored_result(compact, application_id, request_id)
        if stored is not None:
            return stored

        application = self._require_application(compact, application_id)
        pending = application.get('pendingAction') or {}
        if pending.get('requestId') == request_id:
            return self._deliver_and_wait(application, pending)
        if pending:
            raise CCConflictException('A transition is already pending')

        snapshot = self.applications.get_snapshot(compact, application_id)
        context = _auth_context(compact, snapshot.application)
        authorize_action(caller, context, action, compact)
        self._validate_transition(
            snapshot,
            context,
            action,
            target_state,
        )
        pending_action = {
            'requestId': request_id,
            'action': action.value,
            'actorSub': caller.sub,
            'expectedStateName': context.state_name.value,
            'expectedVersion': int(snapshot.application['version']),
            'createdAt': self.config.current_standard_datetime.isoformat(),
            'attempts': 0,
        }
        if snapshot.application.get('lastEnteredKey'):
            pending_action['expectedLastEnteredKey'] = snapshot.application['lastEnteredKey']
        if target_state is not None:
            pending_action['targetState'] = target_state.value

        claimed = self.applications.begin_transition(
            compact,
            application_id,
            expected_version=int(snapshot.application['version']),
            expected_state_name=context.state_name,
            pending_action=pending_action,
            application_review_update=_review_update(
                context.state_name,
                notes_for_applicant=notes_for_applicant,
                notes_for_reviewers=notes_for_reviewers,
                reviewer_selected_application_status=reviewer_selected_application_status,
            ),
        )
        return self._deliver_and_wait(claimed, claimed['pendingAction'])

    def _validate_transition(self, snapshot, context: ApplicationAuthContext, action: WorkflowAction, target_state):
        if action is WorkflowAction.ADMIN_OVERRIDE:
            if target_state is None or not override_target_allowed(context, target_state):
                raise CCInvalidRequestException('Override target is not allowed')
        if action in ACTIONS_REQUIRING_COMPLETE_REVIEWS:
            role = STATE_DEFINITIONS[context.state_name].actor_role
            self.applications.require_complete_reviews(snapshot, role)
        if context.state_name in _STATES_REQUIRING_DISTINCT_REVIEWERS and action not in (
            WorkflowAction.ADMIN_OVERRIDE,
            WorkflowAction.ADMIN_DEACTIVATE,
        ):
            validate_reviewer_assignment(
                context.first_reviewer_sub,
                context.second_reviewer_sub,
                context.final_reviewer_sub,
            )

    def _deliver_and_wait(self, application: Mapping, pending_action: Mapping) -> TransitionResult:
        delivered = self.deliver(application, pending_action)
        if delivered.accepted and delivered.pending:
            return self._poll_until_settled(
                str(application['compact']),
                delivered,
                str(pending_action['action']),
            )
        return delivered

    def _send_once(self, application: Mapping) -> CallbackDelivery:
        pending = application.get('pendingAction') or {}
        token = application.get('taskToken')
        if not token:
            return CallbackDelivery.STALE
        output = {
            'action': pending['action'],
            'actorSub': pending.get('actorSub'),
            'requestId': pending['requestId'],
        }
        if pending.get('targetState'):
            output['targetState'] = pending['targetState']
        return self.workflow.send_task_success(str(token), output)

    def _completed_if_advanced(
        self,
        compact: str,
        application_id: str,
        pending_action: Mapping,
        expected_status: str,
    ) -> TransitionResult | None:
        latest = self.applications.get_application(compact, application_id)
        if latest is None:
            return None
        advanced = _workflow_advanced(latest, pending_action) or _audit_shows_advancement(
            self.applications,
            compact,
            application_id,
            pending_action,
        )
        if not advanced:
            return None
        latest = self.applications.get_application(compact, application_id) or latest
        return self._completed_result(
            latest,
            str(pending_action['requestId']),
            expected_status,
            str(pending_action['action']),
        )

    def _completed_result(
        self,
        application: Mapping,
        request_id: str,
        expected_status: str,
        action: str,
    ) -> TransitionResult:
        result = TransitionResult(
            application_id=str(application['applicationId']),
            request_id=request_id,
            pending=False,
            accepted=True,
            status=application.get('status'),
            expected_status=expected_status,
            state_name=application.get('stateName'),
            generation=_generation(application),
        )
        self._store_result(application, result, action)
        return result

    def _store_result(self, application: Mapping, result: TransitionResult, action: str) -> None:
        try:
            self.applications.put_request_record(
                str(application['compact']),
                str(application['applicationId']),
                result.request_id,
                action=action,
                result=result.as_dict(),
                ttl=_ttl(self.config),
            )
        except CCConflictException:
            return

    def _stored_result(self, compact: str, application_id: str, request_id: str) -> TransitionResult | None:
        stored = self.applications.get_request_record(compact, application_id, request_id)
        if not stored or not stored.get('result'):
            return None
        result = stored['result']
        if result.get('pending'):
            return None
        return TransitionResult(
            application_id=application_id,
            request_id=request_id,
            pending=bool(result.get('pending')),
            accepted=bool(result.get('accepted')),
            status=result.get('status'),
            expected_status=result.get('expectedStatus'),
            state_name=result.get('stateName'),
            generation=result.get('generation'),
        )

    def _clear_if_not_running(self, application: Mapping, request_id: str) -> bool:
        """Clear the claim only when the execution is proven stopped and the workflow did not advance."""
        if not _execution_is_stopped(self.workflow, application.get('executionArn')):
            return False
        compact = str(application['compact'])
        application_id = str(application['applicationId'])
        latest = self.applications.get_application(compact, application_id)
        pending = {} if latest is None else latest.get('pendingAction') or {}
        if latest is None or pending.get('requestId') != request_id:
            return False
        if _workflow_advanced(latest, pending) or _audit_shows_advancement(
            self.applications,
            compact,
            application_id,
            pending,
        ):
            return False
        return self.applications.clear_pending_action(compact, application_id, request_id)

    def _poll_until_settled(self, compact: str, delivered: TransitionResult, action: str) -> TransitionResult:
        deadline = time.monotonic() + self._poll_timeout
        while True:
            latest = self._require_application(compact, delivered.application_id)
            pending = latest.get('pendingAction') or {}
            if pending.get('requestId') != delivered.request_id:
                return self._completed_result(latest, delivered.request_id, delivered.expected_status or '', action)
            if time.monotonic() >= deadline:
                return delivered
            self._sleep(_POLL_INTERVAL_SECONDS)

    def _should_retry(self, outcome: CallbackDelivery, application: Mapping) -> bool:
        if outcome is CallbackDelivery.RETRYABLE:
            return True
        if outcome is not CallbackDelivery.STALE or not application.get('taskToken'):
            return False
        return not _execution_is_stopped(self.workflow, application.get('executionArn'))

    def _poll_for_status(
        self,
        compact: str,
        application_id: str,
        expected_status: str,
        generation: int,
    ) -> TransitionResult:
        deadline = time.monotonic() + self._poll_timeout
        while True:
            latest = self._require_application(compact, application_id)
            if latest.get('status'):
                return TransitionResult(
                    application_id=application_id,
                    request_id='',
                    pending=False,
                    accepted=True,
                    status=latest.get('status'),
                    expected_status=expected_status,
                    state_name=latest.get('stateName'),
                    generation=_generation(latest),
                )
            if time.monotonic() >= deadline:
                return TransitionResult(
                    application_id=application_id,
                    request_id='',
                    pending=True,
                    accepted=True,
                    expected_status=expected_status,
                    generation=generation,
                )
            self._sleep(_POLL_INTERVAL_SECONDS)

    def _start_execution(self, **kwargs) -> None:
        for attempt in range(2):
            try:
                self.workflow.start_execution(**kwargs)
                return
            except WorkflowStartAmbiguous:
                if attempt == 0:
                    self._sleep(self._backoff)
                    continue
        described = self._describe_started_execution(**kwargs)
        expected = self.workflow.execution_input(**kwargs)
        if not inputs_match(described.get('input'), expected):
            raise CCConflictException('Execution already exists with different input')

    def _describe_started_execution(self, **kwargs) -> dict:
        arn = self.workflow.execution_arn(kwargs['compact'], kwargs['application_id'], kwargs['generation'])
        try:
            return self.workflow.describe_execution(arn)
        except ClientError as error:
            if str(error.response.get('Error', {}).get('Code') or '') == 'ExecutionDoesNotExist':
                self._start_unknown(kwargs['application_id'])
                raise WorkflowStartAmbiguous('Execution was not created') from error
            raise

    def _exhausted(self, application_id: str, request_id: str) -> None:
        logger.error(
            'Application callback delivery exhausted for %s request %s',
            application_id,
            request_id,
        )
        metrics.add_metric(name='ApplicationCallbackDeliveryExhausted', unit=MetricUnit.Count, value=1)

    def _start_unknown(self, application_id: str) -> None:
        logger.error('Application execution did not start for %s', application_id)

    def _require_application(self, compact: str, application_id: str) -> dict:
        application = self.applications.get_application(compact, application_id)
        if application is None:
            raise CCNotFoundException('Application not found')
        return application


def _noop_schedule(**_kwargs) -> None:
    return None


def _auth_context(compact: str, application: Mapping) -> ApplicationAuthContext:
    return ApplicationAuthContext(
        compact=compact,
        state_name=StateName(application['stateName']),
        provider_id=application.get('providerId'),
        first_reviewer_sub=application.get('firstReviewerSub'),
        second_reviewer_sub=application.get('secondReviewerSub'),
        final_reviewer_sub=application.get('finalReviewerSub'),
    )


def _review_update(
    state_name: StateName,
    *,
    notes_for_applicant: str | None,
    notes_for_reviewers: str | None,
    reviewer_selected_application_status: str | None,
) -> dict | None:
    role = STATE_DEFINITIONS[state_name].actor_role
    if role not in REVIEWER_ROLES:
        return None
    update = {'role': role}
    if reviewer_selected_application_status:
        update['reviewerSelectedApplicationStatus'] = reviewer_selected_application_status
    if notes_for_applicant is not None:
        update['notesForApplicant'] = notes_for_applicant
    if notes_for_reviewers is not None:
        update['notesForReviewers'] = notes_for_reviewers
    if len(update) == 1:
        return None
    return update


def _target_status(state_name: StateName, action: WorkflowAction, target_state: StateName | None) -> str:
    if action is WorkflowAction.ADMIN_DEACTIVATE:
        return STATE_DEFINITIONS[StateName.DEACTIVATED].status.value
    if action is WorkflowAction.ADMIN_OVERRIDE:
        return STATE_DEFINITIONS[target_state].status.value
    return STATE_DEFINITIONS[STATE_DEFINITIONS[state_name].transitions[action]].status.value


def _expected_status(pending_action: Mapping) -> str:
    action = WorkflowAction(pending_action['action'])
    target = pending_action.get('targetState')
    return _target_status(
        StateName(pending_action['expectedStateName']),
        action,
        None if target is None else StateName(target),
    )


def _workflow_advanced(application: Mapping, pending_action: Mapping) -> bool:
    expected_state = pending_action.get('expectedStateName')
    if application.get('stateName') != expected_state:
        return True
    expected_key = pending_action.get('expectedLastEnteredKey')
    current_key = application.get('lastEnteredKey')
    return bool(expected_key and current_key and current_key != expected_key)


def _audit_shows_advancement(applications, compact: str, application_id: str, pending_action: Mapping) -> bool:
    created_at = pending_action.get('createdAt') or ''
    expected_state = pending_action.get('expectedStateName')
    for item in applications.query_all_items(compact, application_id):
        if item.get('type') != APPLICATION_TRANSITION_RECORD_TYPE:
            continue
        if item.get('fromState') != expected_state:
            continue
        entered = str(item.get('enteredTime') or '')
        if created_at and entered > created_at:
            return True
    return False


def _execution_is_stopped(workflow, execution_arn: str | None) -> bool:
    if not execution_arn:
        return True
    try:
        described = workflow.describe_execution(execution_arn)
    except ClientError as error:
        return str(error.response.get('Error', {}).get('Code') or '') == 'ExecutionDoesNotExist'
    except BotoCoreError:
        return False
    return described.get('status') != 'RUNNING'


def _generation(application: Mapping) -> int | None:
    generation = application.get('generation')
    if generation is None:
        return None
    return int(generation)


def _ttl(config) -> int:
    return int(config.current_standard_datetime.timestamp()) + _REQUEST_TTL_SECONDS
