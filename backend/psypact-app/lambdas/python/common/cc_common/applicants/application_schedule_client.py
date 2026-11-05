"""Best-effort deletion of one application generation's expiry schedule."""

import boto3
from botocore.exceptions import ClientError

from cc_common.config import logger


class ApplicationScheduleClient:
    """Delete an EventBridge Scheduler schedule without affecting the application."""

    def __init__(self, scheduler_client=None):
        self._scheduler_client = scheduler_client

    def delete_schedule(self, name: str, *, application_id: str) -> None:
        """Delete ``name``. A missing schedule or any other error is logged and swallowed."""
        client = self._scheduler_client if self._scheduler_client is not None else boto3.client('scheduler')
        try:
            client.delete_schedule(Name=name)
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
