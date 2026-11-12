"""Thin Step Functions wrapper for one application execution."""

import json
import re
from enum import StrEnum

from botocore.exceptions import BotoCoreError, ClientError
from common_lambdas.exceptions import CCConflictException, CCInvalidRequestException

_EXECUTION_NAME = re.compile(r'^[0-9A-Za-z_-]{1,80}$')
_STALE_TOKEN_CODES = frozenset({'InvalidToken', 'TaskDoesNotExist', 'TaskTimedOut'})
_RETRYABLE_CODES = frozenset(
    {
        'ThrottlingException',
        'TooManyRequestsException',
        'ProvisionedThroughputExceededException',
        'RequestLimitExceeded',
        'Throttling',
        'PriorRequestNotComplete',
        'ServiceException',
        'ServiceUnavailable',
        'InternalFailure',
        'InternalServerError',
    }
)


class CallbackDelivery(StrEnum):
    """How one SendTaskSuccess call ended."""

    SUCCESS = 'SUCCESS'
    RETRYABLE = 'RETRYABLE'
    STALE = 'STALE'


class WorkflowStartAmbiguous(Exception):
    """StartExecution failed in a way that does not prove the execution is absent."""


class ApplicationWorkflowClient:
    """Build deterministic execution names and classify callback errors."""

    def __init__(self, state_machine_arn: str, stepfunctions_client):
        self._state_machine_arn = state_machine_arn
        self._client = stepfunctions_client

    def execution_name(self, application_id: str, generation: int) -> str:
        """Return ``{applicationId}-g{generation}`` when it is a legal execution name."""
        name = f'{application_id}-g{generation}'
        if _EXECUTION_NAME.fullmatch(name) is None:
            raise CCInvalidRequestException('Application execution name is not valid')
        return name

    def execution_arn(self, compact: str, application_id: str, generation: int) -> str:
        """Return the execution ARN for this application generation."""
        if not compact:
            raise CCInvalidRequestException('Compact is required')
        name = self.execution_name(application_id, generation)
        if ':stateMachine:' not in self._state_machine_arn:
            raise CCInvalidRequestException('State machine ARN is not valid')
        return self._state_machine_arn.replace(':stateMachine:', ':execution:', 1) + f':{name}'

    def execution_input(
        self,
        *,
        compact: str,
        application_id: str,
        generation: int,
        workflow_expires_at: str,
        start_at: str,
    ) -> str:
        """Serialize the start envelope with sorted keys so retries are byte-identical."""
        return json.dumps(
            {
                'applicationId': application_id,
                'compact': compact,
                'generation': generation,
                'startAt': start_at,
                'workflowExpiresAt': workflow_expires_at,
            },
            sort_keys=True,
            separators=(',', ':'),
        )

    def start_execution(
        self,
        *,
        compact: str,
        application_id: str,
        generation: int,
        workflow_expires_at: str,
        start_at: str,
    ) -> dict:
        """Start the execution. An existing execution with the same input counts as success."""
        body = self.execution_input(
            compact=compact,
            application_id=application_id,
            generation=generation,
            workflow_expires_at=workflow_expires_at,
            start_at=start_at,
        )
        name = self.execution_name(application_id, generation)
        try:
            return self._client.start_execution(
                stateMachineArn=self._state_machine_arn,
                name=name,
                input=body,
            )
        except ClientError as error:
            if _error_code(error) == 'ExecutionAlreadyExists':
                described = self.describe_execution(self.execution_arn(compact, application_id, generation))
                if inputs_match(described.get('input'), body):
                    return described
                raise CCConflictException('Execution already exists with different input') from error
            if classify_client_error(error) is CallbackDelivery.RETRYABLE:
                raise WorkflowStartAmbiguous('StartExecution failed without a definitive result') from error
            raise
        except BotoCoreError as error:
            raise WorkflowStartAmbiguous('StartExecution failed without a definitive result') from error

    def send_task_success(self, token: str, output: dict) -> CallbackDelivery:
        """Deliver a callback. Retryable and stale-token errors are returned, not raised."""
        body = json.dumps(output, sort_keys=True, separators=(',', ':'))
        try:
            self._client.send_task_success(taskToken=token, output=body)
        except ClientError as error:
            outcome = classify_client_error(error)
            if outcome is None:
                raise
            return outcome
        except BotoCoreError:
            return CallbackDelivery.RETRYABLE
        return CallbackDelivery.SUCCESS

    def describe_execution(self, arn: str) -> dict:
        return self._client.describe_execution(executionArn=arn)

    def stop_execution(self, arn: str, cause: str) -> dict:
        return self._client.stop_execution(executionArn=arn, cause=cause)


def inputs_match(described_input: str | None, expected_input: str) -> bool:
    """Return whether two execution inputs carry the same envelope."""
    if described_input == expected_input:
        return True
    if not described_input:
        return False
    try:
        return json.loads(described_input) == json.loads(expected_input)
    except json.JSONDecodeError:
        return False


def classify_client_error(error: ClientError) -> CallbackDelivery | None:
    """Classify a Step Functions client error. Unknown errors return None so the caller raises."""
    code = _error_code(error)
    if code in _STALE_TOKEN_CODES:
        return CallbackDelivery.STALE
    status = int(error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') or 0)
    if code in _RETRYABLE_CODES or status >= 500:
        return CallbackDelivery.RETRYABLE
    return None


def _error_code(error: ClientError) -> str:
    return str(error.response.get('Error', {}).get('Code') or '')
