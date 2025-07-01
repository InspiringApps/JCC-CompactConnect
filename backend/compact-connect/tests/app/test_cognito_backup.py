"""
Integration tests for Cognito backup functionality in the CDK app.

This module tests the CDK constructs and integration for the Cognito backup system
including the backup bucket, Lambda function, EventBridge scheduling, and backup plans.
"""

import json
from unittest import TestCase

from aws_cdk.assertions import Match, Template
from aws_cdk.aws_backup import CfnBackupPlan, CfnBackupSelection
from aws_cdk.aws_events import CfnRule
from aws_cdk.aws_lambda import CfnFunction
from aws_cdk.aws_s3 import CfnBucket

from tests.app.base import TstAppABC


class TestCognitoBackup(TstAppABC, TestCase):
    @classmethod
    def get_context(cls):
        with open('cdk.json') as f:
            context = json.load(f)['context']
        with open('cdk.context.sandbox-example.json') as f:
            context.update(json.load(f))

        # Suppresses lambda bundling for tests
        context['aws:cdk:bundling-stacks'] = []

        return context

    def test_cognito_backup_buckets_created(self):
        """Test that Cognito backup buckets are created for both user pools."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack

        # Verify staff users backup system exists
        self.assertTrue(hasattr(persistent_stack.staff_users, 'backup_system'))
        self.assertTrue(hasattr(persistent_stack.staff_users.backup_system, 'backup_bucket'))

        # Verify provider users backup system exists
        self.assertTrue(hasattr(persistent_stack.provider_users_deprecated, 'backup_system'))
        self.assertTrue(hasattr(persistent_stack.provider_users_deprecated.backup_system, 'backup_bucket'))

        # Get the template from the persistent stack
        persistent_stack_template = Template.from_stack(persistent_stack)

        # Should have Cognito backup buckets for both user pools
        cognito_buckets = persistent_stack_template.find_resources(
            CfnBucket.CFN_RESOURCE_TYPE_NAME,
            props=Match.object_like(
                {
                    'Properties': {
                        'BucketEncryption': {
                            'ServerSideEncryptionConfiguration': [
                                {'ServerSideEncryptionByDefault': {'SSEAlgorithm': 'aws:kms'}}
                            ]
                        },
                        'VersioningConfiguration': {'Status': 'Enabled'},
                    }
                }
            ),
        )

        # Should find Cognito backup buckets (at least 2 for staff and provider user pools)
        self.assertGreaterEqual(len(cognito_buckets), 2, 'Cognito backup buckets should be created for both user pools')

    def test_cognito_backup_lambdas_created(self):
        """Test that Cognito backup Lambda functions are created for both user pools."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack

        # Verify staff users backup lambda exists
        self.assertTrue(hasattr(persistent_stack.staff_users.backup_system, 'export_lambda'))

        # Verify provider users backup lambda exists
        self.assertTrue(hasattr(persistent_stack.provider_users_deprecated.backup_system, 'export_lambda'))

        # Get the template from the persistent stack
        persistent_stack_template = Template.from_stack(persistent_stack)

        # Find all Lambda functions
        lambda_functions = persistent_stack_template.find_resources(CfnFunction.CFN_RESOURCE_TYPE_NAME)

        # Count Cognito backup lambdas (should have at least 2)
        cognito_backup_lambdas = []
        for _lambda_id, lambda_resource in lambda_functions.items():
            description = lambda_resource.get('Properties', {}).get('Description', '')
            if 'user pool data for backup purposes' in description:
                cognito_backup_lambdas.append(lambda_resource)

        self.assertGreaterEqual(len(cognito_backup_lambdas), 2, 'Should have backup lambdas for both user pools')

        # Verify configuration of one of the lambdas
        if cognito_backup_lambdas:
            lambda_config = cognito_backup_lambdas[0]['Properties']
            self.assertEqual(lambda_config['Runtime'], 'python3.12')
            self.assertEqual(lambda_config['Handler'], 'lambda_function.lambda_handler')
            self.assertEqual(lambda_config['Timeout'], 900)  # 15 minutes
            self.assertEqual(lambda_config['MemorySize'], 512)

            # Verify environment variables are set
            env_vars = lambda_config['Environment']['Variables']
            self.assertIn('BACKUP_BUCKET_NAME', env_vars)
            self.assertIn('USER_POOL_ID', env_vars)
            self.assertIn('USER_POOL_TYPE', env_vars)

    def test_cognito_backup_eventbridge_rules_created(self):
        """Test that EventBridge rules for daily Cognito backup are created for both user pools."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack

        # Verify staff users backup rule exists
        self.assertTrue(hasattr(persistent_stack.staff_users.backup_system, 'backup_rule'))

        # Verify provider users backup rule exists
        self.assertTrue(hasattr(persistent_stack.provider_users_deprecated.backup_system, 'backup_rule'))

        persistent_stack_template = Template.from_stack(persistent_stack)

        # Find EventBridge rules for Cognito backup
        cognito_backup_rules = persistent_stack_template.find_resources(
            CfnRule.CFN_RESOURCE_TYPE_NAME,
            props=Match.object_like(
                {
                    'Properties': {
                        'ScheduleExpression': 'cron(0 2 * * ? *)',  # Daily at 2 AM UTC
                        'State': 'ENABLED',
                    }
                }
            ),
        )

        self.assertGreaterEqual(
            len(cognito_backup_rules), 2, 'Cognito backup EventBridge rules should be created for both user pools'
        )

        # Verify at least one rule has correct target configuration
        if cognito_backup_rules:
            rule = list(cognito_backup_rules.values())[0]
            targets = rule['Properties']['Targets']
            self.assertEqual(len(targets), 1)

            # Verify target has the correct input (event data)
            target = targets[0]
            self.assertIn('Input', target)
            input_data = json.loads(target['Input'])
            self.assertIn('user_pool_id', input_data)
            self.assertIn('backup_bucket_name', input_data)
            self.assertIn('user_pool_type', input_data)

    def test_cognito_backup_buckets_have_backup_plans(self):
        """Test that Cognito backup buckets have backup plans configured."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack

        # Verify staff users backup bucket has backup plan
        self.assertTrue(hasattr(persistent_stack.staff_users.backup_system.backup_bucket, 'backup_plan'))

        # Verify provider users backup bucket has backup plan
        self.assertTrue(hasattr(persistent_stack.provider_users_deprecated.backup_system.backup_bucket, 'backup_plan'))

        persistent_stack_template = Template.from_stack(persistent_stack)

        # Find backup plans
        backup_plans = persistent_stack_template.find_resources(CfnBackupPlan.CFN_RESOURCE_TYPE_NAME)

        # Should have multiple backup plans (DynamoDB tables + S3 buckets + Cognito backup buckets)
        self.assertGreaterEqual(
            len(backup_plans), 7, 'Should have backup plans for tables and S3 buckets including Cognito backup buckets'
        )

        # Find backup plans for Cognito backup buckets
        cognito_backup_plans = []
        for _plan_id, plan in backup_plans.items():
            plan_name = plan['Properties']['BackupPlan']['BackupPlanName']
            if 'staff' in plan_name.lower() or 'provider' in plan_name.lower():
                # Check if this looks like a backup bucket plan (not user table plan)
                if 'bucket' in plan_name.lower() or len(plan_name.split('-')) > 2:
                    cognito_backup_plans.append(plan)

        self.assertGreaterEqual(
            len(cognito_backup_plans), 2, 'Should have backup plans for both Cognito backup buckets'
        )

        # Verify backup plan configuration for at least one plan
        if cognito_backup_plans:
            cognito_backup_plan = cognito_backup_plans[0]
            backup_plan_rules = cognito_backup_plan['Properties']['BackupPlan']['BackupPlanRule']
            self.assertEqual(len(backup_plan_rules), 1)

            rule = backup_plan_rules[0]
            self.assertIn('ScheduleExpression', rule)
            self.assertIn('Lifecycle', rule)
            self.assertIn('CopyActions', rule)

            # Verify copy actions for cross-account backup
            copy_actions = rule['CopyActions']
            self.assertEqual(len(copy_actions), 1)
            copy_action = copy_actions[0]
            self.assertIn('DestinationBackupVaultArn', copy_action)

    def test_cognito_backup_buckets_backup_selections(self):
        """Test that Cognito backup buckets have backup selections configured."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack

        persistent_stack_template = Template.from_stack(persistent_stack)

        # Find backup selections
        backup_selections = persistent_stack_template.find_resources(CfnBackupSelection.CFN_RESOURCE_TYPE_NAME)

        # Should have multiple backup selections (tables + S3 buckets + Cognito backup buckets)
        self.assertGreaterEqual(
            len(backup_selections),
            7,
            'Should have backup selections for tables and S3 buckets including Cognito backup buckets',
        )

        # Find backup selections for Cognito backup buckets
        cognito_backup_selections = []
        for _selection_id, selection in backup_selections.items():
            selection_name = selection['Properties']['BackupSelection']['SelectionName']
            if 'staff' in selection_name.lower() or 'provider' in selection_name.lower():
                # Check if this looks like a backup bucket selection (not user table selection)
                if 'bucket' in selection_name.lower() or len(selection_name.split('-')) > 2:
                    cognito_backup_selections.append(selection)

        self.assertGreaterEqual(
            len(cognito_backup_selections), 2, 'Should have backup selections for both Cognito backup buckets'
        )

        # Verify backup selection targets S3 resources
        if cognito_backup_selections:
            cognito_backup_selection = cognito_backup_selections[0]
            backup_selection_props = cognito_backup_selection['Properties']['BackupSelection']
            self.assertIn('Resources', backup_selection_props)
            resources = backup_selection_props['Resources']
            self.assertEqual(len(resources), 1)

            # Verify resource is an S3 bucket ARN
            resource_arn = resources[0]
            self.assertIn('s3', resource_arn)

    def test_cognito_backup_lambda_permissions(self):
        """Test that the Cognito backup Lambdas have appropriate IAM permissions."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack

        persistent_stack_template = Template.from_stack(persistent_stack)

        # Find the role and policies
        from aws_cdk.aws_iam import CfnPolicy

        policies = persistent_stack_template.find_resources(CfnPolicy.CFN_RESOURCE_TYPE_NAME)

        # Should have policies that grant Cognito and S3 permissions
        found_cognito_policy = False
        found_s3_policy = False

        for _policy_id, policy in policies.items():
            policy_doc = policy['Properties']['PolicyDocument']
            statements = policy_doc.get('Statement', [])

            for statement in statements:
                actions = statement.get('Action', [])

                # Check for Cognito permissions
                if any('cognito-idp:ListUsers' in str(action) for action in actions):
                    found_cognito_policy = True

                # Check for S3 permissions
                if any('s3:PutObject' in str(action) for action in actions):
                    found_s3_policy = True

        self.assertTrue(found_cognito_policy, 'Lambdas should have Cognito permissions')
        self.assertTrue(found_s3_policy, 'Lambdas should have S3 permissions')

    def test_cognito_backup_alarms_created(self):
        """Test that CloudWatch alarms are created for Cognito backup failures."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack

        # Verify staff users backup alarm exists
        self.assertTrue(hasattr(persistent_stack.staff_users.backup_system, 'failure_alarm'))

        # Verify provider users backup alarm exists
        self.assertTrue(hasattr(persistent_stack.provider_users_deprecated.backup_system, 'failure_alarm'))

        persistent_stack_template = Template.from_stack(persistent_stack)

        # Find CloudWatch alarms
        from aws_cdk.aws_cloudwatch import CfnAlarm

        alarms = persistent_stack_template.find_resources(CfnAlarm.CFN_RESOURCE_TYPE_NAME)

        # Find Cognito backup failure alarms
        cognito_backup_alarms = []
        for _alarm_id, alarm in alarms.items():
            alarm_desc = alarm['Properties'].get('AlarmDescription', '')
            if 'user pool backup export Lambda has failed' in alarm_desc:
                cognito_backup_alarms.append(alarm)

        self.assertGreaterEqual(
            len(cognito_backup_alarms), 2, 'Cognito backup failure alarms should be created for both user pools'
        )

        # Verify alarm configuration for at least one alarm
        if cognito_backup_alarms:
            cognito_backup_alarm = cognito_backup_alarms[0]
            alarm_props = cognito_backup_alarm['Properties']
            self.assertEqual(alarm_props['ComparisonOperator'], 'GreaterThanOrEqualToThreshold')
            self.assertEqual(alarm_props['Threshold'], 1)
            self.assertEqual(alarm_props['EvaluationPeriods'], 1)

            # Verify alarm has SNS action
            self.assertIn('AlarmActions', alarm_props)
            alarm_actions = alarm_props['AlarmActions']
            self.assertGreater(len(alarm_actions), 0)

    def test_export_data_backup_policy_configured(self):
        """Test that the export_data backup policy is properly configured in context."""
        # Verify that the context includes the export_data backup policy
        context = self.context
        environment_name = context['environment_name']
        backup_policies = context['ssm_context']['environments'][environment_name]['backup_policies']

        self.assertIn('export_data', backup_policies)

        export_policy = backup_policies['export_data']
        self.assertIn('schedule', export_policy)
        self.assertIn('delete_after_days', export_policy)
        self.assertIn('cold_storage_after_days', export_policy)

        # Verify schedule is daily (4 AM UTC to avoid conflicts with other backups)
        self.assertEqual(export_policy['schedule'], 'cron(0 4 * * ? *)')

        # Verify retention policies
        self.assertEqual(export_policy['delete_after_days'], 365)
        self.assertEqual(export_policy['cold_storage_after_days'], 30)

    def test_cognito_backup_integrates_with_user_pools(self):
        """Test that Cognito backup is properly integrated with created user pools."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack

        # Verify user pools are accessible
        self.assertTrue(hasattr(persistent_stack, 'staff_users'))
        self.assertTrue(hasattr(persistent_stack, 'provider_users_deprecated'))

        # Verify each user pool has a backup system
        self.assertTrue(hasattr(persistent_stack.staff_users, 'backup_system'))
        self.assertTrue(hasattr(persistent_stack.provider_users_deprecated, 'backup_system'))

        # Verify the backup systems are configured with the correct user pool IDs
        self.assertEqual(
            persistent_stack.staff_users.backup_system.user_pool_id, persistent_stack.staff_users.user_pool_id
        )
        self.assertEqual(
            persistent_stack.provider_users_deprecated.backup_system.user_pool_id,
            persistent_stack.provider_users_deprecated.user_pool_id,
        )

        # Verify the backup systems have the correct user pool types
        self.assertEqual(persistent_stack.staff_users.backup_system.user_pool_type, 'staff')
        self.assertEqual(persistent_stack.provider_users_deprecated.backup_system.user_pool_type, 'provider')
