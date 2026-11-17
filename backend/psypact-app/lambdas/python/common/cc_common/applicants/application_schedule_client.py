"""Create and delete one application generation's expiry schedule."""

import json
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from cc_common.config import logger


class ApplicationScheduleClient:
    """EventBridge Scheduler access for one application generation's expiry schedule."""

    def __init__(self, scheduler_client=None):
        self._scheduler_client = scheduler_client

    def create_expiry_schedule(
        self,
        compact: str,
        application_id: str,
        generation: int,
        fire_at: str,
        *,
        group_name: str,
        target_arn: str,
        role_arn: str,
    ) -> str:
        """Create the one-time expiry schedule. An existing schedule of this name is success.

        The schedule name matches the execution name, ``{applicationId}-g{generation}``.
        ``ActionAfterCompletion=DELETE`` removes it after it fires.
        """
        name = f'{application_id}-g{generation}'
        expression, timezone_name = _at_expression(fire_at)
        client = self._scheduler_client if self._scheduler_client is not None else boto3.client('scheduler')
        try:
            client.create_schedule(
                Name=name,
                GroupName=group_name,
                ScheduleExpression=expression,
                ScheduleExpressionTimezone=timezone_name,
                FlexibleTimeWindow={'Mode': 'OFF'},
                ActionAfterCompletion='DELETE',
                Target={
                    'Arn': target_arn,
                    'RoleArn': role_arn,
                    'Input': json.dumps(
                        {
                            'applicationId': application_id,
                            'compact': compact,
                            'generation': generation,
                            'scheduleName': name,
                        },
                        sort_keys=True,
                        separators=(',', ':'),
                    ),
                },
            )
        except ClientError as error:
            if error.response.get('Error', {}).get('Code') != 'ConflictException':
                raise
        return name

    def delete_schedule(self, name: str, *, application_id: str, group_name: str | None = None) -> None:
        """Delete ``name``. A missing schedule or any other error is logged and swallowed."""
        client = self._scheduler_client if self._scheduler_client is not None else boto3.client('scheduler')
        request = {'Name': name}
        if group_name:
            request['GroupName'] = group_name
        try:
            client.delete_schedule(**request)
        except ClientError as error:
            logger.error(
                'Failed to delete application expiry schedule for %s',
                application_id,
                application_id=application_id,
                schedule_name=name,
                error_code=error.response.get('Error', {}).get('Code'),
            )
        except Exception as error:  # noqa: BLE001 the caller must not see a schedule-cleanup failure
            logger.error(
                'Failed to delete application expiry schedule for %s',
                application_id,
                application_id=application_id,
                schedule_name=name,
                exc_info=error,
            )


def _at_expression(fire_at: str) -> tuple[str, str]:
    """Return an EventBridge Scheduler ``at()`` expression and its timezone."""
    parsed = datetime.fromisoformat(fire_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    utc_time = parsed.astimezone(UTC).replace(microsecond=0)
    return f'at({utc_time.strftime("%Y-%m-%dT%H:%M:%S")})', 'UTC'
