"""
Unit tests for the backup infrastructure stack.

Tests backup vault creation, KMS key setup, IAM role configuration,
and cross-account vault ARN generation for Phase 3 implementation.
"""

import unittest
from unittest.mock import patch

from aws_cdk import App
from aws_cdk.assertions import Template

from stacks.backup_infrastructure_stack import BackupInfrastructureStack


class TestBackupInfrastructureStack(unittest.TestCase):
    """Test cases for the BackupInfrastructureStack."""

    def setUp(self):
        """Set up test fixtures."""
        self.app = App()

    def test_backup_infrastructure_stack_creation(self):
        """Test basic backup infrastructure stack creation."""
        stack = BackupInfrastructureStack(self.app, 'TestBackupInfrastructure')
        
        # Verify stack was created
        self.assertIsNotNone(stack)
        self.assertIsNotNone(stack.backup_vault)
        self.assertIsNotNone(stack.backup_service_role)
        self.assertIsNotNone(stack.backup_kms_key)

    def test_backup_vault_creation(self):
        """Test that backup vault is created with correct configuration."""
        stack = BackupInfrastructureStack(self.app, 'TestBackupInfrastructure')
        
        template = Template.from_stack(stack)
        
        # Verify backup vault exists
        template.has_resource_properties('AWS::Backup::BackupVault', {
            'BackupVaultName': 'CompactConnectBackupVault'
        })

    def test_kms_key_creation(self):
        """Test that KMS key is created with key rotation enabled."""
        stack = BackupInfrastructureStack(self.app, 'TestBackupInfrastructure')
        
        template = Template.from_stack(stack)
        
        # Verify KMS key exists with rotation enabled
        template.has_resource_properties('AWS::KMS::Key', {
            'Description': 'KMS key for CompactConnect backup encryption',
            'EnableKeyRotation': True
        })

    def test_backup_service_role_creation(self):
        """Test that backup service role is created with correct policies."""
        stack = BackupInfrastructureStack(self.app, 'TestBackupInfrastructure')
        
        template = Template.from_stack(stack)
        
        # Verify backup service role exists
        template.has_resource_properties('AWS::IAM::Role', {
            'AssumeRolePolicyDocument': {
                'Statement': [
                    {
                        'Action': 'sts:AssumeRole',
                        'Effect': 'Allow',
                        'Principal': {
                            'Service': 'backup.amazonaws.com'
                        }
                    }
                ]
            },
            'ManagedPolicyArns': [
                {
                    'Fn::Join': [
                        '',
                        [
                            'arn:',
                            {'Ref': 'AWS::Partition'},
                            ':iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup'
                        ]
                    ]
                },
                {
                    'Fn::Join': [
                        '',
                        [
                            'arn:',
                            {'Ref': 'AWS::Partition'},
                            ':iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores'
                        ]
                    ]
                },
                {
                    'Fn::Join': [
                        '',
                        [
                            'arn:',
                            {'Ref': 'AWS::Partition'},
                            ':iam::aws:policy/service-role/AWSBackupServiceRolePolicyForS3Backup'
                        ]
                    ]
                },
                {
                    'Fn::Join': [
                        '',
                        [
                            'arn:',
                            {'Ref': 'AWS::Partition'},
                            ':iam::aws:policy/service-role/AWSBackupServiceRolePolicyForS3Restore'
                        ]
                    ]
                }
            ]
        })

    def test_cross_account_vault_arn_generation_with_backup_account(self):
        """Test cross-account vault ARN generation when backup account is configured."""
        # Mock context with backup account configuration
        with patch.object(self.app.node, 'try_get_context') as mock_context:
            mock_context.return_value = {
                'backup_account_id': '123456789012',
                'backup_region': 'us-west-2'
            }
            
            stack = BackupInfrastructureStack(self.app, 'TestBackupInfrastructure')
            
            expected_arn = (
                'arn:aws:backup:us-west-2:123456789012:'
                'backup-vault:CompactConnectBackupVault'
            )
            self.assertEqual(stack.cross_account_vault_arn, expected_arn)

    def test_cross_account_vault_arn_none_without_backup_account(self):
        """Test cross-account vault ARN is None when no backup account is configured."""
        # Mock context without backup account configuration
        with patch.object(self.app.node, 'try_get_context') as mock_context:
            mock_context.return_value = {}
            
            stack = BackupInfrastructureStack(self.app, 'TestBackupInfrastructure')
            
            self.assertIsNone(stack.cross_account_vault_arn)

    def test_backup_account_id_from_context(self):
        """Test backup account ID is correctly read from context."""
        # Mock context with backup account configuration
        with patch.object(self.app.node, 'try_get_context') as mock_context:
            mock_context.return_value = {
                'backup_account_id': '987654321098',
                'backup_region': 'us-east-1'
            }
            
            stack = BackupInfrastructureStack(self.app, 'TestBackupInfrastructure')
            
            self.assertEqual(stack.backup_account_id, '987654321098')
            self.assertEqual(stack.backup_region, 'us-east-1')

    def test_default_backup_region(self):
        """Test default backup region is us-west-2 when not specified."""
        # Mock context without backup region specified
        with patch.object(self.app.node, 'try_get_context') as mock_context:
            mock_context.return_value = {
                'backup_account_id': '123456789012'
            }
            
            stack = BackupInfrastructureStack(self.app, 'TestBackupInfrastructure')
            
            self.assertEqual(stack.backup_region, 'us-west-2')

    def test_kms_key_permissions_for_backup_role(self):
        """Test that backup service role has KMS permissions."""
        stack = BackupInfrastructureStack(self.app, 'TestBackupInfrastructure')
        
        template = Template.from_stack(stack)
        
        # The KMS key should have a policy that allows the backup service role to use it
        # This is typically implemented via grant_encrypt_decrypt method
        # We can verify the IAM policy was created for the role
        template.has_resource('AWS::IAM::Policy')


if __name__ == '__main__':
    unittest.main()