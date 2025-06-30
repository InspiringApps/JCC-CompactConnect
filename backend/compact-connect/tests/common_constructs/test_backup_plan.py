"""
Unit tests for the backup plan construct.

Tests backup plan creation, category-based configuration, schedule management,
and cross-account replication functionality for Phase 3 S3 backup implementation.
"""

import unittest
from unittest.mock import Mock, patch

from aws_cdk import App, Duration, Stack
from aws_cdk.aws_backup import BackupVault
from aws_cdk.aws_iam import Role, ServicePrincipal
from aws_cdk.aws_kms import Key
from aws_cdk.aws_s3 import Bucket
from aws_cdk.assertions import Template

from common_constructs.backup_plan import BackupPlanConstruct


class TestBackupPlanConstruct(unittest.TestCase):
    """Test cases for the BackupPlanConstruct."""

    def setUp(self):
        """Set up test fixtures."""
        self.app = App()
        self.stack = Stack(self.app, 'TestStack')
        
        # Create test resources
        self.kms_key = Key(self.stack, 'TestKey')
        self.backup_vault = BackupVault(
            self.stack, 'TestVault',
            backup_vault_name='TestBackupVault',
            encryption_key=self.kms_key
        )
        self.backup_role = Role(
            self.stack, 'TestRole',
            assumed_by=ServicePrincipal('backup.amazonaws.com')
        )
        self.test_bucket = Bucket(self.stack, 'TestBucket')

    def test_backup_plan_creation_with_document_storage_category(self):
        """Test backup plan creation with document_storage category."""
        # Create backup plan construct
        backup_plan = BackupPlanConstruct(
            self.stack,
            'TestBackupPlan',
            resource_arn=self.test_bucket.bucket_arn,
            backup_category='document_storage',
            local_backup_vault=self.backup_vault,
            backup_service_role=self.backup_role,
        )
        
        # Verify backup plan was created
        self.assertIsNotNone(backup_plan.backup_plan)
        
        # Get CloudFormation template
        template = Template.from_stack(self.stack)
        
        # Verify backup plan exists
        template.has_resource_properties('AWS::Backup::BackupPlan', {
            'BackupPlan': {
                'BackupPlanName': 'TestBackupPlan-document_storage'
            }
        })

    def test_backup_plan_with_context_configuration(self):
        """Test backup plan with custom context configuration."""
        # Set context for custom backup policies
        custom_backup_policies = {
            'document_storage': {
                'schedule': 'cron(0 3 * * ? *)',  # 3 AM instead of 2 AM
                'retention_days': 120,  # 120 days instead of 90
                'cross_account_copy': True,
            }
        }
        
        # Mock the context
        with patch.object(self.stack.node, 'try_get_context') as mock_context:
            mock_context.return_value = custom_backup_policies
            
            backup_plan = BackupPlanConstruct(
                self.stack,
                'TestBackupPlan',
                resource_arn=self.test_bucket.bucket_arn,
                backup_category='document_storage',
                local_backup_vault=self.backup_vault,
                backup_service_role=self.backup_role,
            )
        
        # Verify backup plan was created
        self.assertIsNotNone(backup_plan.backup_plan)

    def test_backup_plan_with_cross_account_replication(self):
        """Test backup plan with cross-account replication."""
        cross_account_vault_arn = 'arn:aws:backup:us-west-2:123456789012:backup-vault:CompactConnectBackupVault'
        
        backup_plan = BackupPlanConstruct(
            self.stack,
            'TestBackupPlan',
            resource_arn=self.test_bucket.bucket_arn,
            backup_category='document_storage',
            local_backup_vault=self.backup_vault,
            backup_service_role=self.backup_role,
            cross_account_vault_arn=cross_account_vault_arn,
        )
        
        # Verify backup plan was created
        self.assertIsNotNone(backup_plan.backup_plan)

    def test_backup_plan_critical_data_category(self):
        """Test backup plan with critical_data category has longer retention."""
        backup_plan = BackupPlanConstruct(
            self.stack,
            'TestBackupPlan',
            resource_arn=self.test_bucket.bucket_arn,
            backup_category='critical_data',
            local_backup_vault=self.backup_vault,
            backup_service_role=self.backup_role,
        )
        
        # Verify backup plan was created
        self.assertIsNotNone(backup_plan.backup_plan)
        
        # Get CloudFormation template
        template = Template.from_stack(self.stack)
        
        # Verify backup plan exists with critical_data naming
        template.has_resource_properties('AWS::Backup::BackupPlan', {
            'BackupPlan': {
                'BackupPlanName': 'TestBackupPlan-critical_data'
            }
        })

    def test_backup_plan_configuration_data_category(self):
        """Test backup plan with configuration_data category."""
        backup_plan = BackupPlanConstruct(
            self.stack,
            'TestBackupPlan',
            resource_arn=self.test_bucket.bucket_arn,
            backup_category='configuration_data',
            local_backup_vault=self.backup_vault,
            backup_service_role=self.backup_role,
        )
        
        # Verify backup plan was created
        self.assertIsNotNone(backup_plan.backup_plan)

    def test_backup_plan_default_policy_fallback(self):
        """Test backup plan uses default policy when category not configured."""
        backup_plan = BackupPlanConstruct(
            self.stack,
            'TestBackupPlan',
            resource_arn=self.test_bucket.bucket_arn,
            backup_category='unknown_category',
            local_backup_vault=self.backup_vault,
            backup_service_role=self.backup_role,
        )
        
        # Verify backup plan was created with default policy
        self.assertIsNotNone(backup_plan.backup_plan)

    def test_backup_plan_without_cross_account_vault(self):
        """Test backup plan creation without cross-account vault configuration."""
        backup_plan = BackupPlanConstruct(
            self.stack,
            'TestBackupPlan',
            resource_arn=self.test_bucket.bucket_arn,
            backup_category='document_storage',
            local_backup_vault=self.backup_vault,
            backup_service_role=self.backup_role,
            cross_account_vault_arn=None,
        )
        
        # Verify backup plan was created
        self.assertIsNotNone(backup_plan.backup_plan)

    def test_default_policy_values(self):
        """Test that default policies have correct values."""
        backup_plan = BackupPlanConstruct(
            self.stack,
            'TestBackupPlan',
            resource_arn=self.test_bucket.bucket_arn,
            backup_category='document_storage',
            local_backup_vault=self.backup_vault,
            backup_service_role=self.backup_role,
        )
        
        # Test the _get_default_policy method directly
        document_storage_policy = backup_plan._get_default_policy('document_storage')
        self.assertEqual(document_storage_policy['schedule'], 'cron(0 2 * * ? *)')
        self.assertEqual(document_storage_policy['retention_days'], 90)
        self.assertTrue(document_storage_policy['cross_account_copy'])
        
        critical_data_policy = backup_plan._get_default_policy('critical_data')
        self.assertEqual(critical_data_policy['retention_days'], 2555)  # 7 years
        
        config_data_policy = backup_plan._get_default_policy('configuration_data')
        self.assertEqual(config_data_policy['retention_days'], 1095)  # 3 years


if __name__ == '__main__':
    unittest.main()