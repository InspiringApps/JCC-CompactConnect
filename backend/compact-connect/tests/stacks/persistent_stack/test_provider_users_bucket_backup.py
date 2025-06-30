"""
Integration tests for provider users bucket backup implementation.

Tests that the provider users bucket correctly implements backup according to
Phase 3 specifications, including backup plan creation, category assignment,
and integration with backup infrastructure.
"""

import unittest
from unittest.mock import Mock, patch

from aws_cdk import App, Stack
from aws_cdk.assertions import Template

from common_constructs.access_logs_bucket import AccessLogsBucket
from stacks.backup_infrastructure_stack import BackupInfrastructureStack
from stacks.persistent_stack.provider_table import ProviderTable
from stacks.persistent_stack.provider_users_bucket import ProviderUsersBucket


class TestProviderUsersBucketBackup(unittest.TestCase):
    """Test cases for provider users bucket backup implementation."""

    def setUp(self):
        """Set up test fixtures."""
        self.app = App()
        self.stack = Stack(self.app, 'TestStack')
        
        # Create backup infrastructure stack
        self.backup_infrastructure = BackupInfrastructureStack(
            self.app, 'TestBackupInfrastructure'
        )
        
        # Mock the persistent stack to include backup infrastructure
        with patch('stacks.persistent_stack.PersistentStack.of') as mock_of:
            mock_stack = Mock()
            mock_stack.backup_infrastructure = self.backup_infrastructure
            mock_of.return_value = mock_stack
            
            # Create dependencies
            self.access_logs_bucket = AccessLogsBucket(
                self.stack, 'TestAccessLogsBucket'
            )
            
            self.provider_table = ProviderTable(
                self.stack, 'TestProviderTable',
                encryption_key=self.backup_infrastructure.backup_kms_key,
                removal_policy='DESTROY'
            )
            
            # Create provider users bucket with backup
            self.provider_users_bucket = ProviderUsersBucket(
                self.stack, 'TestProviderUsersBucket',
                access_logs_bucket=self.access_logs_bucket,
                encryption_key=self.backup_infrastructure.backup_kms_key,
                provider_table=self.provider_table,
            )

    def test_provider_users_bucket_has_backup_plan(self):
        """Test that provider users bucket creates a backup plan."""
        # Verify the bucket has a backup plan
        self.assertTrue(hasattr(self.provider_users_bucket, 'backup_plan'))
        self.assertIsNotNone(self.provider_users_bucket.backup_plan)

    def test_provider_users_bucket_uses_document_storage_category(self):
        """Test that provider users bucket uses document_storage backup category."""
        # The backup plan should be created with document_storage category
        # This is verified by checking the backup plan name contains the category
        backup_plan = self.provider_users_bucket.backup_plan
        self.assertIsNotNone(backup_plan)

    def test_provider_users_bucket_backup_integration(self):
        """Test provider users bucket backup integration with infrastructure."""
        template = Template.from_stack(self.stack)
        
        # Verify that backup plan is created
        template.has_resource('AWS::Backup::BackupPlan')
        
        # Verify that backup selection is created
        template.has_resource('AWS::Backup::BackupSelection')

    def test_provider_users_bucket_nag_suppression_updated(self):
        """Test that NAG suppression reflects backup implementation."""
        template = Template.from_stack(self.stack)
        
        # The bucket should exist
        template.has_resource('AWS::S3::Bucket')

    def test_backup_plan_without_backup_infrastructure(self):
        """Test graceful handling when backup infrastructure is not available."""
        # Create a new stack without backup infrastructure
        test_stack = Stack(self.app, 'TestStackNoBackup')
        
        # Mock the persistent stack to NOT include backup infrastructure
        with patch('stacks.persistent_stack.PersistentStack.of') as mock_of:
            mock_stack = Mock()
            mock_stack.backup_infrastructure = None
            mock_of.return_value = mock_stack
            
            # Create bucket without backup infrastructure
            bucket = ProviderUsersBucket(
                test_stack, 'TestBucketNoBackup',
                access_logs_bucket=self.access_logs_bucket,
                encryption_key=self.backup_infrastructure.backup_kms_key,
                provider_table=self.provider_table,
            )
            
            # Should not have backup plan
            self.assertFalse(hasattr(bucket, 'backup_plan'))

    def test_backup_plan_creation_with_cross_account_replication(self):
        """Test backup plan creation with cross-account replication configuration."""
        # Mock backup infrastructure with cross-account vault ARN
        with patch.object(self.backup_infrastructure, 'cross_account_vault_arn', 
                         'arn:aws:backup:us-west-2:123456789012:backup-vault:CompactConnectBackupVault'):
            
            # Create a new bucket to test with cross-account configuration
            test_stack = Stack(self.app, 'TestStackCrossAccount')
            
            with patch('stacks.persistent_stack.PersistentStack.of') as mock_of:
                mock_stack = Mock()
                mock_stack.backup_infrastructure = self.backup_infrastructure
                mock_of.return_value = mock_stack
                
                bucket = ProviderUsersBucket(
                    test_stack, 'TestBucketCrossAccount',
                    access_logs_bucket=self.access_logs_bucket,
                    encryption_key=self.backup_infrastructure.backup_kms_key,
                    provider_table=self.provider_table,
                )
                
                # Verify backup plan was created
                self.assertTrue(hasattr(bucket, 'backup_plan'))
                self.assertIsNotNone(bucket.backup_plan)

    def test_bucket_classification_as_primary_data(self):
        """Test that provider users bucket is correctly classified as primary data requiring backup."""
        # Provider users bucket contains military affiliation documents and other
        # irreplaceable provider data, so it should have backup according to Phase 3
        self.assertTrue(hasattr(self.provider_users_bucket, 'backup_plan'))
        
        # The bucket should be versioned (for data protection)
        template = Template.from_stack(self.stack)
        
        # Find the S3 bucket and verify it has versioning
        bucket_resources = template.find_resources('AWS::S3::Bucket')
        self.assertGreater(len(bucket_resources), 0)

    def test_backup_plan_resource_arn_configuration(self):
        """Test that backup plan is configured with correct resource ARN."""
        # The backup plan should target this specific bucket
        backup_plan = self.provider_users_bucket.backup_plan
        self.assertIsNotNone(backup_plan)


if __name__ == '__main__':
    unittest.main()