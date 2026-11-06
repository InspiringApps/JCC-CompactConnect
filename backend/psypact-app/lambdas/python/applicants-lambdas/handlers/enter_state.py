"""Record the state a workflow execution has entered.

The state machine calls this for every node. The response is identifiers only.
The task token is stored by the data client and is never written to the log.
"""

import contextvars
import logging
import os
from collections.abc import Mapping

from aws_lambda_powertools.utilities.typing import LambdaContext
from cc_common.applicants.application_schedule_client import ApplicationScheduleClient
from cc_common.applicants.application_state import StateName, WorkflowAction
from cc_common.config import logger, metrics
from common_lambdas.exceptions import CCConflictException, CCInvalidRequestException, CCNotFoundException

_ENTER = 'ENTER'
_TERMINAL = 'TERMINAL'
_task_token: contextvars.ContextVar[str | None] = contextvars.ContextVar('application_task_token', default=None)


class _TaskTokenRedactor(logging.Filter):
    """Remove the in-flight task token from any log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        secret = _task_token.get()
        if secret:
            _redact_record(record, secret)
        return True


def _redact_record(record: logging.LogRecord, secret: str) -> None:
    record.msg = _redact_value(record.msg, secret)
    if isinstance(record.args, dict):
        record.args = _redact_value(record.args, secret)
    elif isinstance(record.args, tuple):
        record.args = tuple(_redact_value(value, secret) for value in record.args)
    for key, value in list(record.__dict__.items()):
        if key in {'msg', 'args', 'exc_info'}:
            continue
        redacted = _redact_value(value, secret)
        if redacted is not value:
            setattr(record, key, redacted)


def _redact_value(value, secret: str):
    if isinstance(value, str):
        if secret not in value:
            return value
        return value.replace(secret, '[REDACTED]')
    if isinstance(value, Mapping):
        return {key: _redact_value(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, secret) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, secret) for item in value)
    return value


if not any(isinstance(existing, _TaskTokenRedactor) for existing in logger.filters):
    logger.addFilter(_TaskTokenRedactor())


def _runtime_config():
    from common_lambdas import config as config_module

    return config_module.config


def _state_name(value) -> StateName:
    try:
        return value if isinstance(value, StateName) else StateName(value)
    except ValueError as error:
        raise CCInvalidRequestException('Unknown application state') from error


def _terminal_reason(error, transition: Mapping | None = None) -> str | None:
    """Read the terminal reason from the caught error, or from an admin deactivation."""
    if isinstance(error, str):
        stripped = error.strip()
        if stripped:
            return stripped
    if isinstance(error, Mapping):
        for key in ('reason', 'Error', 'error'):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(transition, Mapping) and transition.get('action') == WorkflowAction.ADMIN_DEACTIVATE.value:
        return WorkflowAction.ADMIN_DEACTIVATE.value
    return None


def _delete_expiry_schedule(application: Mapping, application_id: str) -> None:
    schedule_name = application.get('scheduleName')
    if not schedule_name:
        logger.error('Application %s has no expiry schedule to delete', application_id, application_id=application_id)
        return
    try:
        delete_kwargs = {'application_id': application_id}
        group_name = os.environ.get('APPLICATION_SCHEDULE_GROUP_NAME')
        if group_name:
            delete_kwargs['group_name'] = group_name
        ApplicationScheduleClient().delete_schedule(str(schedule_name), **delete_kwargs)
    except Exception as error:  # noqa: BLE001 schedule cleanup must not undo a completed entry
        logger.error(
            'Failed to delete application expiry schedule for %s',
            application_id,
            application_id=application_id,
            exc_info=error,
        )


@metrics.log_metrics
@logger.inject_lambda_context
def enter_state(event: dict, context: LambdaContext):  # noqa: ARG001 the decorator supplies the context
    """Write one state entry. ``TERMINAL`` also deletes that generation's expiry schedule."""
    mode = event.get('mode')
    if mode not in {_ENTER, _TERMINAL}:
        raise CCInvalidRequestException('Unknown enter state mode')

    compact = event['compact']
    application_id = event['applicationId']
    state_name = _state_name(event.get('stateName'))
    token = event.get('taskToken')
    token_reset = _task_token.set(token if isinstance(token, str) and token else None)
    try:
        client = _runtime_config().application_client
        application = client.get_application(compact, application_id)
        if application is None:
            raise CCNotFoundException('Application not found')
        if int(application['generation']) != int(event['generation']):
            raise CCConflictException('Application generation does not match this execution')

        logger.info(
            'Entering application state',
            mode=mode,
            compact=compact,
            application_id=application_id,
            generation=int(event['generation']),
            state_name=state_name.value,
        )
        stored = client.enter_state(
            compact,
            application_id,
            execution_arn=event['executionArn'],
            state_name=state_name,
            entered_time=event['enteredTime'],
            task_token=None if mode == _TERMINAL else token,
            terminal=mode == _TERMINAL,
            reason=(_terminal_reason(event.get('error'), event.get('transition')) if mode == _TERMINAL else None),
        )
        if mode == _TERMINAL:
            _delete_expiry_schedule(stored, application_id)
    finally:
        _task_token.reset(token_reset)

    return {
        'applicationId': application_id,
        'compact': compact,
        'generation': int(event['generation']),
        'executionArn': event['executionArn'],
        'stateName': state_name.value,
    }
