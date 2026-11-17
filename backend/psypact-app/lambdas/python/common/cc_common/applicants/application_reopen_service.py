"""Start a new staff-review generation after the previous execution has stopped."""

import time
from collections.abc import Mapping

from botocore.exceptions import ClientError
from common_lambdas.exceptions import CCAccessDeniedException, CCConflictException, CCNotFoundException

from cc_common.applicants.application_metrics import emit_count
from cc_common.applicants.application_state import StateName
from cc_common.applicants.application_transition_service import (
    TransitionResult,
    _completed_record_result,
    _default_schedule_creator,
)
from cc_common.applicants.application_workflow_client import WorkflowStartAmbiguous
from cc_common.config import logger

_REOPEN_ACTION = 'REOPEN'
_FORCED_STOP = 'REOPEN_FORCED_STOP'
_FORCED_STOP_METRIC = 'ApplicationReopenForcedStop'
_POLL_TIMEOUT_SECONDS = 5
_BACKOFF_SECONDS = 0.05
_BROKEN_STATUSES = frozenset({'FAILED', 'TIMED_OUT', 'ABORTED'})
_BROKEN_REASONS = {
    'FAILED': 'EXECUTION_FAILED',
    'TIMED_OUT': 'EXECUTION_TIMED_OUT',
    'ABORTED': 'EXECUTION_ABORTED',
}
_REQUEST_TTL_SECONDS = 365 * 24 * 60 * 60


class ApplicationReopenService:
    """Reopen one application into a new StaffReview generation.

    Each step checks the application before it writes, so the same request id can resume
    after a lock, a committed generation, or a started execution.
    """

    def __init__(
        self,
        config,
        *,
        workflow_client=None,
        transition_service=None,
        schedule_creator=None,
        sleeper=None,
        poll_timeout_seconds: float = _POLL_TIMEOUT_SECONDS,
        backoff_seconds: float = _BACKOFF_SECONDS,
    ):
        self.config = config
        self.applications = config.application_client
        self.workflow = workflow_client if workflow_client is not None else config.application_workflow_client
        if transition_service is None:
            from cc_common.applicants.application_transition_service import ApplicationTransitionService

            transition_service = ApplicationTransitionService(
                config,
                workflow_client=self.workflow,
                sleeper=sleeper,
                poll_timeout_seconds=poll_timeout_seconds,
                backoff_seconds=backoff_seconds,
            )
        self.transitions = transition_service
        self._schedule_creator = schedule_creator if schedule_creator is not None else _default_schedule_creator(config)
        self._sleep = sleeper if sleeper is not None else time.sleep
        self._poll_timeout = poll_timeout_seconds
        self._backoff = backoff_seconds

    def reopen(self, compact: str, application_id: str, caller, request_id: str, reason: str) -> TransitionResult:
        """Stop the current execution if it is still running, then start StaffReview."""
        _require_admin(caller, compact)
        stored = _completed_record_result(
            self.applications.get_request_record(compact, application_id, request_id),
            application_id,
            request_id,
        )
        if stored is not None:
            return stored

        application = self.applications.acquire_reopen_lock(compact, application_id, request_id)
        self._settle_old_execution(application, caller, request_id)
        application = self._require_application(compact, application_id)
        generation = _target_generation(application)
        execution_arn = self.workflow.execution_arn(compact, application_id, generation)
        schedule_name = self.workflow.execution_name(application_id, generation)
        expires = _reopen_expiry(application)
        old_schedule = _old_schedule_name(application, application_id)
        if application.get('executionArn') != execution_arn:
            self._create_schedule(compact, application_id, generation, schedule_name, expires, execution_arn)
            generation = self.applications.commit_reopen_generation(
                compact,
                application_id,
                request_id,
                execution_arn,
                schedule_name,
                expires,
            )
        self._start_staff_review(compact, application_id, generation, expires, request_id)
        self._delete_old_schedule(old_schedule, application_id)
        return self._finish(compact, application_id, caller, request_id, reason, generation)

    def _settle_old_execution(self, application: Mapping, caller, request_id: str) -> None:
        lock = application.get('reopenLock') or {}
        old_arn = lock.get('oldExecutionArn')
        if not old_arn or application.get('executionArn') != old_arn:
            return
        status = _execution_status(self.workflow, old_arn)
        if status == 'RUNNING' and application.get('taskToken'):
            if self._deactivate_gracefully(application, caller, request_id, old_arn):
                return
            application = self._require_application(str(application['compact']), str(application['applicationId']))
            status = _execution_status(self.workflow, old_arn)
        if status == 'RUNNING':
            self._force_stop(application, old_arn, request_id)
            return
        if status in _BROKEN_STATUSES and application.get('deactivationReason') != _FORCED_STOP:
            self.applications.mark_deactivated_by_reconciler(
                str(application['compact']),
                str(application['applicationId']),
                execution_arn=old_arn,
                generation=int(lock.get('oldGeneration') or application.get('generation') or 1),
                reason=_BROKEN_REASONS[status],
                last_execution_error=None,
            )

    def _deactivate_gracefully(self, application: Mapping, caller, request_id: str, execution_arn: str) -> bool:
        claimed = self.applications.claim_reopen_deactivation(
            str(application['compact']),
            str(application['applicationId']),
            request_id,
            caller.sub,
        )
        self.transitions.deliver(claimed, claimed['pendingAction'])
        return self._wait_for_status(execution_arn, 'SUCCEEDED')

    def _force_stop(self, application: Mapping, execution_arn: str, request_id: str) -> None:
        compact = str(application['compact'])
        application_id = str(application['applicationId'])
        lock = application.get('reopenLock') or {}
        generation = int(lock.get('oldGeneration') or application.get('generation') or 1)
        try:
            self.workflow.stop_execution(execution_arn, _FORCED_STOP)
        except ClientError as error:
            if _error_code(error) != 'ExecutionDoesNotExist':
                raise
        self.applications.mark_deactivated_by_reconciler(
            compact,
            application_id,
            execution_arn=execution_arn,
            generation=generation,
            reason=_FORCED_STOP,
            last_execution_error=None,
        )
        logger.error(
            'Application reopen forced stop for %s generation %s execution %s request %s',
            application_id,
            generation,
            execution_arn,
            request_id,
        )
        emit_count(_FORCED_STOP_METRIC)

    def _create_schedule(
        self,
        compact: str,
        application_id: str,
        generation: int,
        schedule_name: str,
        expires: str,
        execution_arn: str,
    ) -> None:
        self._schedule_creator(
            compact=compact,
            application_id=application_id,
            generation=generation,
            schedule_name=schedule_name,
            workflow_expires_at=expires,
            execution_arn=execution_arn,
        )

    def _start_staff_review(
        self,
        compact: str,
        application_id: str,
        generation: int,
        expires: str,
        request_id: str,
    ) -> None:
        kwargs = {
            'compact': compact,
            'application_id': application_id,
            'generation': generation,
            'workflow_expires_at': expires,
            'start_at': StateName.STAFF_REVIEW.value,
        }
        for attempt in range(2):
            try:
                self.workflow.start_execution(**kwargs)
                return
            except WorkflowStartAmbiguous:
                if attempt == 0:
                    self._sleep(self._backoff)
                    continue
        try:
            self.workflow.describe_execution(self.workflow.execution_arn(compact, application_id, generation))
        except ClientError as error:
            if _error_code(error) == 'ExecutionDoesNotExist':
                logger.error(
                    'Application reopen did not start for %s generation %s request %s',
                    application_id,
                    generation,
                    request_id,
                )
                raise WorkflowStartAmbiguous('Execution was not created') from error
            raise

    def _finish(
        self,
        compact: str,
        application_id: str,
        caller,
        request_id: str,
        reason: str,
        generation: int,
    ) -> TransitionResult:
        deadline = time.monotonic() + self._poll_timeout
        while True:
            latest = self._require_application(compact, application_id)
            if latest.get('stateName') == StateName.STAFF_REVIEW.value and not latest.get('reopenLock'):
                result = TransitionResult(
                    application_id=application_id,
                    request_id=request_id,
                    pending=False,
                    accepted=True,
                    status=latest.get('status'),
                    expected_status=latest.get('status'),
                    state_name=latest.get('stateName'),
                    generation=int(latest.get('generation') or generation),
                )
                self._store_result(latest, result, caller.sub, reason)
                return result
            if time.monotonic() >= deadline:
                return TransitionResult(
                    application_id=application_id,
                    request_id=request_id,
                    pending=True,
                    accepted=True,
                    status=latest.get('status'),
                    expected_status='staff-review',
                    state_name=latest.get('stateName'),
                    generation=generation,
                )
            self._sleep(self._backoff)

    def _store_result(self, application: Mapping, result: TransitionResult, actor_sub: str, reason: str) -> None:
        stored = result.as_dict()
        if reason:
            stored['reason'] = reason
        try:
            self.applications.put_request_record(
                str(application['compact']),
                str(application['applicationId']),
                result.request_id,
                action=_REOPEN_ACTION,
                result=stored,
                ttl=int(self.config.current_standard_datetime.timestamp()) + _REQUEST_TTL_SECONDS,
                actor_sub=actor_sub,
            )
        except CCConflictException:
            return

    def _delete_old_schedule(self, schedule_name: str | None, application_id: str) -> None:
        if not schedule_name:
            return
        from cc_common.applicants.application_schedule_client import ApplicationScheduleClient

        ApplicationScheduleClient().delete_schedule(
            schedule_name,
            application_id=application_id,
            group_name=self.config.application_schedule_group_name
            if _env_is_set('APPLICATION_SCHEDULE_GROUP_NAME')
            else None,
        )

    def _wait_for_status(self, execution_arn: str, wanted: str) -> bool:
        deadline = time.monotonic() + self._poll_timeout
        while True:
            status = _execution_status(self.workflow, execution_arn)
            if status == wanted:
                return True
            if status in _BROKEN_STATUSES:
                return False
            if time.monotonic() >= deadline:
                return False
            self._sleep(self._backoff)

    def _require_application(self, compact: str, application_id: str) -> dict:
        application = self.applications.get_application(compact, application_id)
        if application is None:
            raise CCNotFoundException('Application not found')
        return application


def _require_admin(caller, compact: str) -> None:
    if f'{compact}/admin' not in caller.scopes:
        raise CCAccessDeniedException('Forbidden access attempt!')


def _target_generation(application: Mapping) -> int:
    lock = application.get('reopenLock') or {}
    old_generation = int(lock.get('oldGeneration') or application.get('generation') or 1)
    old_arn = lock.get('oldExecutionArn')
    if old_arn and application.get('executionArn') != old_arn:
        return int(application.get('generation') or old_generation + 1)
    return old_generation + 1


def _reopen_expiry(application: Mapping) -> str:
    lock = application.get('reopenLock') or {}
    old_arn = lock.get('oldExecutionArn')
    if old_arn and application.get('executionArn') != old_arn and application.get('workflowExpiresAt'):
        return str(application['workflowExpiresAt'])
    if lock.get('workflowExpiresAt'):
        return str(lock['workflowExpiresAt'])
    if application.get('workflowExpiresAt'):
        return str(application['workflowExpiresAt'])
    raise CCNotFoundException('Application reopen has no expiry')


def _old_schedule_name(application: Mapping, application_id: str) -> str | None:
    lock = application.get('reopenLock') or {}
    old_generation = lock.get('oldGeneration')
    if old_generation is None:
        return None
    current_generation = int(application.get('generation') or 0)
    if int(old_generation) == current_generation and application.get('scheduleName'):
        return str(application['scheduleName'])
    return f'{application_id}-g{int(old_generation)}'


def _execution_status(workflow, execution_arn: str) -> str | None:
    try:
        described = workflow.describe_execution(execution_arn)
    except ClientError as error:
        if _error_code(error) == 'ExecutionDoesNotExist':
            return None
        raise
    status = described.get('status')
    return str(status) if status else None


def _error_code(error: ClientError) -> str:
    return str(error.response.get('Error', {}).get('Code') or '')


def _env_is_set(name: str) -> bool:
    import os

    return bool(os.environ.get(name))
