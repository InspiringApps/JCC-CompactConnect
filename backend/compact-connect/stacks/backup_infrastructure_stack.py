"""
Backup Infrastructure Stack

This stack provides the foundational backup infrastructure for environment accounts,
including local backup vaults, IAM service roles, and KMS keys for backup encryption.
This implements the distributed backup architecture from Phase 2 to support Phase 3
S3 bucket backup implementation.
"""

from aws_cdk import Stack
from aws_cdk.aws_backup import BackupVault
from aws_cdk.aws_iam import (
    ManagedPolicy,
    PolicyDocument,
    PolicyStatement,
    Role,
    ServicePrincipal,
)
from aws_cdk.aws_kms import Key
from constructs import Construct


class BackupInfrastructureStack(Stack):
    """
    Creates the backup infrastructure for environment accounts.
    
    This stack provides:
    - Local backup vaults for storing backups
    - IAM service roles for AWS Backup operations
    - KMS keys for backup encryption
    - Cross-account vault ARN configuration from context
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Create KMS key for backup encryption
        self.backup_kms_key = Key(
            self,
            'BackupKMSKey',
            description='KMS key for CompactConnect backup encryption',
            enable_key_rotation=True,
        )
        
        # Create local backup vault for general resources
        self.backup_vault = BackupVault(
            self,
            'BackupVault',
            backup_vault_name='CompactConnectBackupVault',
            encryption_key=self.backup_kms_key,
        )
        
        # Create backup service role for AWS Backup
        self.backup_service_role = Role(
            self,
            'BackupServiceRole',
            role_name='AWSBackupServiceRole',
            assumed_by=ServicePrincipal('backup.amazonaws.com'),
            managed_policies=[
                ManagedPolicy.from_aws_managed_policy_name('service-role/AWSBackupServiceRolePolicyForBackup'),
                ManagedPolicy.from_aws_managed_policy_name('service-role/AWSBackupServiceRolePolicyForRestores'),
                ManagedPolicy.from_aws_managed_policy_name('service-role/AWSBackupServiceRolePolicyForS3Backup'),
                ManagedPolicy.from_aws_managed_policy_name('service-role/AWSBackupServiceRolePolicyForS3Restore'),
            ],
        )
        
        # Grant backup service role permissions to use the KMS key
        self.backup_kms_key.grant_encrypt_decrypt(self.backup_service_role)
        
        # Get cross-account backup configuration from context
        backup_config = self.node.try_get_context('backup_config') or {}
        self.backup_account_id = backup_config.get('backup_account_id')
        self.backup_region = backup_config.get('backup_region', 'us-west-2')
        
        # Create cross-account vault ARN for copy actions
        if self.backup_account_id:
            self.cross_account_vault_arn = (
                f'arn:aws:backup:{self.backup_region}:{self.backup_account_id}:'
                f'backup-vault:CompactConnectBackupVault'
            )
        else:
            self.cross_account_vault_arn = None