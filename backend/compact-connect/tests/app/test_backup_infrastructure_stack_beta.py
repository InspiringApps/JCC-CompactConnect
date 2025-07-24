import json
from unittest import TestCase

from aws_cdk.assertions import Template
from aws_cdk.aws_backup import CfnBackupVault
from aws_cdk.aws_cloudwatch import CfnAlarm
from aws_cdk.aws_events import CfnRule
from aws_cdk.aws_iam import CfnRole
from aws_cdk.aws_kms import CfnAlias, CfnKey

from tests.app.base import TstAppABC


class TestBackupInfrastructureStackBeta(TstAppABC, TestCase):
    """Test backup infrastructure stack behavior when backup is disabled (beta environment)."""

    @classmethod
    def get_context(cls):
        with open('cdk.json') as f:
            context = json.load(f)['context']
        with open('cdk.context.beta-example.json') as f:
            beta_context = json.load(f)
            # Remove backup_config to simulate beta environment without backup
            if 'backup_config' in beta_context['ssm_context']:
                del beta_context['ssm_context']['backup_config']
            # Add sandbox mode and environment name to create sandbox backend stage
            beta_context['sandbox'] = True
            beta_context['environment_name'] = 'beta'
            # Add required sandbox configuration
            beta_context['sandbox_active_compact_member_jurisdictions'] = {
                "aslp": ["al", "ak", "ar", "co", "de", "ky", "la", "me", "md", "mn", "ms", "mo", "ne", "oh"],
                "octp": ["al", "ar", "ky", "la", "ms", "ne", "oh"],
                "coun": ["al", "ar", "fl", "ga", "ky", "ne", "oh", "ut"]
            }
            context.update(beta_context)

        # Suppresses lambda bundling for tests
        context['aws:cdk:bundling-stacks'] = []

        return context

    def setUp(self):
        """Set up test fixtures."""
        # Use the sandbox backend stage for testing backup infrastructure with disabled backup
        self.backup_stack = self.app.sandbox_backend_stage.backup_infrastructure_stack
        self.template = Template.from_stack(self.backup_stack)

    def test_backup_disabled_flag_is_true(self):
        """Test that backup_disabled flag is set to True when backup_config is None."""
        self.assertTrue(
            self.backup_stack.backup_disabled,
            'backup_disabled should be True when backup_config is None'
        )

    def test_backup_config_is_none(self):
        """Test that backup_config is None when not provided in SSM context."""
        self.assertIsNone(
            self.backup_stack.backup_config,
            'backup_config should be None when not provided in SSM context'
        )

    def test_no_backup_resources_created(self):
        """Test that no backup-related resources are created when backup is disabled."""
        # Should create 0 KMS keys
        self.template.resource_count_is(CfnKey.CFN_RESOURCE_TYPE_NAME, 0)

        # Should create 0 KMS aliases
        self.template.resource_count_is(CfnAlias.CFN_RESOURCE_TYPE_NAME, 0)

        # Should create 0 backup vaults
        self.template.resource_count_is(CfnBackupVault.CFN_RESOURCE_TYPE_NAME, 0)

        # Should create 0 IAM roles
        self.template.resource_count_is(CfnRole.CFN_RESOURCE_TYPE_NAME, 0)

        # Should create 0 monitoring resources (alarms and EventBridge rules)
        self.template.resource_count_is(CfnAlarm.CFN_RESOURCE_TYPE_NAME, 0)
        self.template.resource_count_is(CfnRule.CFN_RESOURCE_TYPE_NAME, 0)

    def test_backup_properties_are_none(self):
        """Test that all backup-related properties are None when backup is disabled."""
        # KMS keys should be None
        self.assertIsNone(self.backup_stack.local_backup_key)
        self.assertIsNone(self.backup_stack.local_ssn_backup_key)

        # Service roles should be None
        self.assertIsNone(self.backup_stack.backup_service_role)
        self.assertIsNone(self.backup_stack.ssn_backup_service_role)

        # Backup vaults should be None
        self.assertIsNone(self.backup_stack.local_backup_vault)
        self.assertIsNone(self.backup_stack.local_ssn_backup_vault)

        # Cross-account vault references should be None
        self.assertIsNone(self.backup_stack.cross_account_backup_vault)
        self.assertIsNone(self.backup_stack.cross_account_ssn_backup_vault)

    def test_stack_creates_successfully_without_backup(self):
        """Test that the stack creates successfully even when backup is disabled."""
        # The backup infrastructure stack should be present and not None
        self.assertIsNotNone(self.app.sandbox_backend_stage.backup_infrastructure_stack)

        # The stack should have a valid stack name
        self.assertIsNotNone(self.backup_stack.stack_name)

        # The template should be valid (no CloudFormation errors)
        self.assertIsNotNone(self.template)

    def test_environment_name_is_preserved(self):
        """Test that environment name and other basic properties are preserved."""
        # Environment name should still be set correctly
        self.assertIsNotNone(self.backup_stack.environment_name)
        
        # Alarm topic should still be available
        self.assertIsNotNone(self.backup_stack.alarm_topic)

    def test_template_is_minimal_without_backup_resources(self):
        """Test that the CloudFormation template is minimal when backup is disabled."""
        # Get all resources in the template
        all_resources = self.template.find_resources('*')
        
        # Template should be essentially empty or contain only minimal nested stack metadata
        # Since this is a nested stack, it might have some CDK metadata but no functional resources
        self.assertEqual(
            len(all_resources),
            0,
            'Template should have no functional resources when backup is disabled'
        )

    def test_backend_stage_integration_with_disabled_backup(self):
        """Test that the backup infrastructure stack integrates correctly with backend stage when backup is disabled."""
        # The backup infrastructure stack should be present in the sandbox backend stage
        self.assertIsNotNone(self.app.sandbox_backend_stage.backup_infrastructure_stack)

        # Validate that the stack reference exists but backup is disabled
        self.assertTrue(self.backup_stack.backup_disabled)

        # Validate that the backend stage can still access the backup_infrastructure_stack reference
        # even though backup is disabled
        backend_stage = self.app.sandbox_backend_stage
        self.assertIs(
            backend_stage.backup_infrastructure_stack,
            self.backup_stack,
            'Backend stage should have reference to backup infrastructure stack'
        )

    def test_no_cdk_nag_suppressions_when_backup_disabled(self):
        """Test that no CDK NAG suppressions are added when backup is disabled."""
        # When backup is disabled, no backup resources are created,
        # so there should be no need for CDK NAG suppressions
        # This is implicitly tested by the fact that no resources are created,
        # but we can verify the template is clean
        template_dict = self.template.to_json()
        
        # Template should not contain any CDK metadata related to suppressions
        # if no resources were created that would need suppressions
        self.assertNotIn('cdk-nag', str(template_dict).lower()) 