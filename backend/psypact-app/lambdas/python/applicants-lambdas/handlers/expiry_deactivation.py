"""Deactivate an application when its one-time expiry schedule fires.

A completed, stale, or reopened application is a successful no-op. The schedule
is then deleted by EventBridge because the invocation completed.
"""

from aws_lambda_powertools.utilities.typing import LambdaContext
from cc_common.applicants.application_metrics import emit_count
from cc_common.applicants.application_state import Caller, StateName, is_terminal
from cc_common.config import logger, metrics
from cc_common.psypact_config import PsypactConfig

_SYSTEM_SUB = 'application-expiry'
_FAILURE_METRIC = 'ApplicationExpiryDeactivationFailed'


def expiry_deactivation(event: dict, context: LambdaContext):  # noqa: ARG001 Lambda entry supplies context
    """Deactivate the named generation, or return without writing when it is no longer current."""
    return _deactivate(event)


@metrics.log_metrics
@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext):
    """Lambda entry. Metrics are flushed after the deactivation attempt."""
    return expiry_deactivation(event, context)


def _deactivate(event: dict) -> dict:
    compact = event['compact']
    application_id = event['applicationId']
    generation = int(event['generation'])
    schedule_name = event['scheduleName']
    service = _runtime_config().application_transition_service
    application = service.applications.get_application(compact, application_id)
    execution_arn = service.workflow.execution_arn(compact, application_id, generation)
    if not _should_deactivate(application, generation, schedule_name, execution_arn):
        return {'applicationId': application_id, 'deactivated': False}

    caller = Caller(sub=_SYSTEM_SUB, scopes={f'{compact}/admin'})
    request_id = f'expiry-{application_id}-g{generation}'
    try:
        result = service.admin_deactivate(compact, application_id, caller, request_id)
        if not result.accepted:
            raise RuntimeError('Application expiry deactivation was not accepted')
    except Exception:
        logger.error(
            'Application expiry deactivation failed for %s generation %s',
            application_id,
            generation,
        )
        emit_count(_FAILURE_METRIC)
        raise
    return {'applicationId': application_id, 'deactivated': True}


def _should_deactivate(application: dict | None, generation: int, schedule_name: str, execution_arn: str) -> bool:
    if not application:
        return False
    if int(application.get('generation') or 0) != generation:
        return False
    if application.get('executionArn') != execution_arn:
        return False
    expected_schedule = f'{application.get("applicationId")}-g{generation}'
    if application.get('scheduleName') != schedule_name or schedule_name != expected_schedule:
        return False
    state_name = application.get('stateName')
    if not state_name or is_terminal(StateName(state_name)):
        return False
    if not application.get('taskToken'):
        return False
    return not application.get('reopenLock')


def _runtime_config() -> PsypactConfig:
    import common_lambdas.config as config_module

    return config_module.config
