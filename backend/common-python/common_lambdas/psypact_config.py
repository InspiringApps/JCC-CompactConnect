import os
from functools import cached_property

import boto3

from common_lambdas.config import _Config


class PsypactConfig(_Config):
    """PSYPACT runtime config: Cosmetology licensing DataClient plus JCC account/Authorize.Net wiring."""

    @cached_property
    def data_client(self):
        from common_lambdas.psypact_data_client import PsypactDataClient

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
