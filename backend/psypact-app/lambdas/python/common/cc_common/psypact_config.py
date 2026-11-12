import os
from functools import cached_property

import boto3
from common_lambdas.config import _Config


class _StaffUserClient:
    """Staff user reads. Assignment checks use a consistent read."""

    def __init__(self, config):
        from common_lambdas.data_model.user_client import UserClient

        self._client = UserClient(config)

    def __getattr__(self, name):
        return getattr(self._client, name)

    def get_user_in_compact(self, *, compact: str, user_id: str, consistent_read: bool = False):
        if not consistent_read:
            return self._client.get_user_in_compact(compact=compact, user_id=user_id)
        from common_lambdas.exceptions import CCNotFoundException

        user = self._client.config.users_table.get_item(
            Key={'pk': f'USER#{user_id}', 'sk': f'COMPACT#{compact}'},
            ConsistentRead=True,
        ).get('Item')
        if user is None:
            raise CCNotFoundException('User not found')
        return self._client.schema.load(user)


class PsypactConfig(_Config):
    """PSYPACT runtime config: Cosmetology licensing DataClient plus JCC account/Authorize.Net wiring."""

    @cached_property
    def data_client(self):
        from cc_common.psypact_data_client import PsypactDataClient

        return PsypactDataClient(self)

    @property
    def provider_user_pool_id(self):
        return os.environ['PROVIDER_USER_POOL_ID']

    @property
    def provider_user_pool_ui_client_id(self):
        return os.environ['PROVIDER_USER_POOL_CLIENT_ID']

    @property
    def provider_user_bucket_name(self):
        return os.environ['PROVIDER_USER_BUCKET_NAME']

    @cached_property
    def transaction_client(self):
        from common_lambdas.data_model.transaction_client import TransactionClient

        return TransactionClient(self)

    @property
    def transaction_reports_bucket_name(self):
        return os.environ['TRANSACTION_REPORTS_BUCKET_NAME']

    @property
    def export_results_bucket_name(self):
        return os.environ['EXPORT_RESULTS_BUCKET_NAME']

    @property
    def transaction_history_table_name(self):
        return os.environ['TRANSACTION_HISTORY_TABLE_NAME']

    @property
    def transaction_history_table(self):
        return boto3.resource('dynamodb').Table(self.transaction_history_table_name)

    @property
    def transaction_history_transaction_id_gsi_name(self):
        return os.environ['TRANSACTION_HISTORY_TRANSACTION_ID_GSI_NAME']

    @property
    def compact_transaction_id_gsi_name(self):
        return os.environ['COMPACT_TRANSACTION_ID_GSI_NAME']

    @property
    def application_table_name(self):
        return os.environ['APPLICATION_TABLE_NAME']

    @property
    def application_table(self):
        return boto3.resource('dynamodb').Table(self.application_table_name)

    @property
    def application_status_gsi_name(self):
        return os.environ['APPLICATION_STATUS_GSI_NAME']

    @property
    def application_actor_gsi_name(self):
        return os.environ['APPLICATION_ACTOR_GSI_NAME']

    @property
    def application_applicant_gsi_name(self):
        return os.environ['APPLICATION_APPLICANT_GSI_NAME']

    @property
    def application_state_machine_arn(self):
        return os.environ['APPLICATION_STATE_MACHINE_ARN']

    @property
    def application_schedule_group_name(self):
        return os.environ['APPLICATION_SCHEDULE_GROUP_NAME']

    @property
    def application_expiry_function_arn(self):
        return os.environ['APPLICATION_EXPIRY_FUNCTION_ARN']

    @property
    def application_scheduler_role_arn(self):
        return os.environ['APPLICATION_SCHEDULER_ROLE_ARN']

    @cached_property
    def stepfunctions_client(self):
        return boto3.client('stepfunctions')

    @cached_property
    def application_workflow_client(self):
        from cc_common.applicants.application_workflow_client import ApplicationWorkflowClient

        return ApplicationWorkflowClient(self.application_state_machine_arn, self.stepfunctions_client)

    @cached_property
    def application_transition_service(self):
        from cc_common.applicants.application_transition_service import ApplicationTransitionService

        return ApplicationTransitionService(self)

    @cached_property
    def application_client(self):
        from cc_common.applicants.application_client import ApplicationClient

        return ApplicationClient(self)

    @cached_property
    def user_client(self):
        return _StaffUserClient(self)

    @cached_property
    def application_reopen_service(self):
        from cc_common.applicants.application_reopen_service import ApplicationReopenService

        return ApplicationReopenService(self)
