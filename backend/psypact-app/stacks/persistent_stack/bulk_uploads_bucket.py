from __future__ import annotations

from aws_cdk.aws_kms import IKey
from aws_cdk.aws_logs import QueryDefinition, QueryString
from aws_cdk.aws_s3 import BucketEncryption, CorsRule, HttpMethods
from cdk_nag import NagSuppressions
from common_constructs.access_logs_bucket import AccessLogsBucket
from common_constructs.bucket import Bucket
from constructs import Construct


class BulkUploadsBucket(Bucket):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        access_logs_bucket: AccessLogsBucket,
        bucket_encryption_key: IKey,
        **kwargs,
    ):
        super().__init__(
            scope,
            construct_id,
            encryption=BucketEncryption.KMS,
            encryption_key=bucket_encryption_key,
            server_access_logs_bucket=access_logs_bucket,
            versioned=False,
            cors=[
                CorsRule(
                    allowed_methods=[HttpMethods.GET, HttpMethods.POST],
                    allowed_origins=['*'],
                    allowed_headers=['*'],
                ),
            ],
            **kwargs,
        )
        self.log_groups = []

        QueryDefinition(
            self,
            'RuntimeQuery',
            query_definition_name=f'{construct_id}/Lambdas',
            query_string=QueryString(
                fields=['@timestamp', '@log', 'level', 'status', 'message', '@message'],
                filter_statements=['level in ["INFO", "WARNING", "ERROR"]'],
                sort='@timestamp desc',
            ),
            log_groups=self.log_groups,
        )

        NagSuppressions.add_resource_suppressions(
            self,
            suppressions=[
                {
                    'id': 'HIPAA.Security-S3BucketReplicationEnabled',
                    'reason': 'This bucket houses transitory data only, so replication to a backup bucket is'
                    ' unhelpful.',
                },
                {
                    'id': 'HIPAA.Security-S3BucketVersioningEnabled',
                    'reason': 'This bucket houses transitory data only, so storing of version history is unhelpful.',
                },
            ],
        )
