"""Record a stopped execution that can no longer enter another workflow node.

Step Functions reports FAILED, TIMED_OUT, and ABORTED here. The application is
marked internal-error so it can be reopened. A newer generation is left unchanged.
An abort that belongs to a reopen is counted separately.
"""

import json
import os
from collections.abc import Mapping

from aws_lambda_powertools.utilities.typing import LambdaContext
from cc_common.applicants.application_metrics import emit_count
from cc_common.applicants.application_schedule_client import ApplicationScheduleClient
from cc_common.applicants.application_state import ApplicationStatus, StateName, is_terminal
from cc_common.config import logger, metrics
from cc_common.psypact_config import PsypactConfig

_FAILING_STATUSES = frozenset({'FAILED', 'TIMED_OUT', 'ABORTED'})
_REASONS = {
    'FAILED': 'EXECUTION_FAILED',
    'TIMED_OUT': 'EXECUTION_TIMED_OUT',
    'ABORTED': 'EXECUTION_ABORTED',
}
_BROKEN_METRIC = 'ApplicationExecutionBroken'
_REOPEN_METRIC = 'ApplicationReopenForcedStop'
_ERROR_LIMIT = 1000


def execution_status_reconciler(event: dict, context: LambdaContext):  # noqa: ARG001 Lambda entry supplies context
    """Mark the execution's application internal-error when that execution is still current."""
    return _reconcile(event)


@metrics.log_metrics
@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext):
    """Lambda entry. Metrics are flushed after the reconciliation attempt."""
    return execution_status_reconciler(event, context)


def _reconcile(event: dict) -> dict:
    detail = _detail(event)
    status = detail.get('status')
    if status not in _FAILING_STATUSES:
        return {'acted': False}
    parsed = _parse_execution_name(str(detail.get('name') or ''))
    compact = _compact(detail)
    execution_arn = detail.get('executionArn')
    if parsed is None or not compact or not execution_arn or _wrong_state_machine(detail):
        logger.error('Application execution event could not be reconciled status %s', status)
        return {'acted': False}

    application_id, generation = parsed
    logger.error(
        'Application execution %s for %s generation %s status %s',
        execution_arn,
        application_id,
        generation,
        status,
    )
    client = _runtime_config().application_client
    application = client.get_application(compact, application_id)
    reason = _REASONS[status]
    reopen = _reopen_abort(application, execution_arn)
    if _already_internal_error(application, execution_arn, generation, reason):
        outcome = 'already'
    elif _targets_current(application, execution_arn, generation):
        outcome = client.mark_deactivated_by_reconciler(
            compact,
            application_id,
            execution_arn=str(execution_arn),
            generation=generation,
            reason=reason,
            last_execution_error=_execution_error(detail),
        )
    else:
        outcome = 'reopen-observed' if reopen else 'stale'

    if outcome == 'applied':
        emit_count(_REOPEN_METRIC if reopen else _BROKEN_METRIC)
        _delete_schedule(application, application_id, generation)
    elif outcome == 'reopen-observed':
        emit_count(_REOPEN_METRIC)
    return {'applicationId': application_id, 'generation': generation, 'outcome': outcome}


def _targets_current(application: Mapping | None, execution_arn: str, generation: int) -> bool:
    if not application:
        return False
    if int(application.get('generation') or 0) != generation:
        return False
    if application.get('executionArn') != execution_arn:
        return False
    if _reopen_abort(application, execution_arn):
        return True
    state_name = application.get('stateName')
    if not state_name:
        return True
    return not is_terminal(StateName(state_name))


def _already_internal_error(
    application: Mapping | None,
    execution_arn: str,
    generation: int,
    reason: str,
) -> bool:
    if not application:
        return False
    return (
        int(application.get('generation') or 0) == generation
        and application.get('executionArn') == execution_arn
        and application.get('status') == ApplicationStatus.INTERNAL_ERROR.value
        and application.get('deactivationReason') == reason
    )


def _reopen_abort(application: Mapping | None, execution_arn: str) -> bool:
    if not application:
        return False
    lock = application.get('reopenLock')
    return isinstance(lock, Mapping) and lock.get('oldExecutionArn') == execution_arn


def _delete_schedule(application: Mapping | None, application_id: str, generation: int) -> None:
    schedule_name = (application or {}).get('scheduleName') or f'{application_id}-g{generation}'
    ApplicationScheduleClient().delete_schedule(
        str(schedule_name),
        application_id=application_id,
        group_name=os.environ.get('APPLICATION_SCHEDULE_GROUP_NAME'),
    )


def _detail(event: Mapping) -> Mapping:
    detail = event.get('detail')
    if isinstance(detail, Mapping):
        return detail
    return event


def _parse_execution_name(name: str) -> tuple[str, int] | None:
    application_id, separator, generation = name.rpartition('-g')
    if not separator or not application_id or not generation.isdigit():
        return None
    return application_id, int(generation)


def _compact(detail: Mapping) -> str | None:
    raw_input = detail.get('input')
    if isinstance(raw_input, Mapping):
        compact = raw_input.get('compact')
        return str(compact) if compact else None
    if not isinstance(raw_input, str) or not raw_input:
        return None
    try:
        parsed = json.loads(raw_input)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, Mapping):
        return None
    compact = parsed.get('compact')
    return str(compact) if compact else None


def _wrong_state_machine(detail: Mapping) -> bool:
    expected = os.environ.get('APPLICATION_STATE_MACHINE_ARN')
    incoming = detail.get('stateMachineArn')
    return bool(expected and incoming and incoming != expected)


def _execution_error(detail: Mapping) -> str | None:
    parts = [str(detail.get('error') or ''), str(detail.get('cause') or '')]
    text = ' '.join(part for part in parts if part).strip()
    if not text:
        return None
    return text[:_ERROR_LIMIT]


def _runtime_config() -> PsypactConfig:
    import common_lambdas.config as config_module

    return config_module.config
