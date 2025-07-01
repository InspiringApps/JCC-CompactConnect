from __future__ import annotations

from aws_cdk import RemovalPolicy
from aws_cdk.aws_kms import IKey
from aws_cdk.aws_s3 import BucketEncryption
from cdk_nag import NagSuppressions
from common_constructs.access_logs_bucket import AccessLogsBucket
from common_constructs.bucket import Bucket
from constructs import Construct

from stacks.backup_infrastructure_stack import BackupInfrastructureStack


class CognitoBackupBucket(Bucket):
    """
    S3 bucket to store exported Cognito user pool data for backup purposes.

    This bucket stores daily exports of user data from both staff and provider
    user pools. Each user is stored as a separate JSON file with the object key
    based on the username for easy identification during disaster recovery.

    The bucket integrates with the backup infrastructure to ensure exported
    data is also backed up to the cross-account backup vault.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        access_logs_bucket: AccessLogsBucket,
        encryption_key: IKey,
        removal_policy: RemovalPolicy,
        backup_infrastructure_stack: BackupInfrastructureStack,
        environment_context: dict,
        **kwargs,
    ):
        super().__init__(
            scope,
            construct_id,
            encryption=BucketEncryption.KMS,
            encryption_key=encryption_key,
            server_access_logs_bucket=access_logs_bucket,
            removal_policy=removal_policy,
            versioned=True,  # Enable versioning for better data protection
            **kwargs,
        )

        # Set up backup plan using the export_data backup category
        from common_constructs.backup_plan import S3BackupPlan
        self.backup_plan = S3BackupPlan(
            self,
            'CognitoBackupBucketBackup',
            bucket=self,
            backup_vault=backup_infrastructure_stack.local_backup_vault,
            backup_service_role=backup_infrastructure_stack.backup_service_role,
            cross_account_backup_vault=backup_infrastructure_stack.cross_account_backup_vault,
            backup_policy=environment_context['backup_policies']['export_data'],
        )

        # Add CDK NAG suppressions for this bucket
        NagSuppressions.add_resource_suppressions(
            self,
            suppressions=[
                {
                    'id': 'HIPAA.Security-S3BucketReplicationEnabled',
                    'reason': 'This bucket stores Cognito user exports that are backed up to cross-account vault via AWS Backup. '
                    'Replication is handled by the backup infrastructure rather than S3 replication.',
                },
            ],
        )
