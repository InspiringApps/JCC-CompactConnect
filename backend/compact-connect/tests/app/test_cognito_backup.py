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

    def test_cognito_backup_bucket_created(self):
        """Test that the Cognito backup bucket is created with proper configuration."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack
        backup_infrastructure_stack = persistent_stack.backup_infrastructure_stack
        
        # Verify the backup infrastructure stack has the cognito backup bucket
        self.assertTrue(hasattr(backup_infrastructure_stack, 'cognito_backup_bucket'))
        
        # Get the bucket from the backup infrastructure stack template
        backup_stack_template = Template.from_stack(backup_infrastructure_stack)
        
        # Should have exactly one Cognito backup bucket
        cognito_buckets = backup_stack_template.find_resources(
            CfnBucket.CFN_RESOURCE_TYPE_NAME,
            props=Match.object_like({
                'Properties': {
                    'BucketEncryption': {
                        'ServerSideEncryptionConfiguration': [
                            {
                                'ServerSideEncryptionByDefault': {
                                    'SSEAlgorithm': 'aws:kms'
                                }
                            }
                        ]
                    },
                    'VersioningConfiguration': {
                        'Status': 'Enabled'
                    }
                }
            })
        )
        
        # Should find the Cognito backup bucket
        self.assertGreaterEqual(len(cognito_buckets), 1, "Cognito backup bucket should be created")

    def test_cognito_backup_lambda_created(self):
        """Test that the Cognito backup Lambda function is created with proper configuration."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack
        backup_infrastructure_stack = persistent_stack.backup_infrastructure_stack
        
        # Verify the backup infrastructure stack has the cognito backup lambda
        self.assertTrue(hasattr(backup_infrastructure_stack, 'cognito_backup_lambda'))
        
        # Get the Lambda from the backup infrastructure stack template
        backup_stack_template = Template.from_stack(backup_infrastructure_stack)
        
        # Find the Cognito backup Lambda function
        lambda_logical_id = backup_infrastructure_stack.get_logical_id(
            backup_infrastructure_stack.cognito_backup_lambda.node.default_child
        )
        
        cognito_lambda = self.get_resource_properties_by_logical_id(
            lambda_logical_id,
            backup_stack_template.find_resources(CfnFunction.CFN_RESOURCE_TYPE_NAME)
        )
        
        # Verify Lambda configuration
        self.assertEqual(cognito_lambda['Runtime'], 'python3.12')
        self.assertEqual(cognito_lambda['Handler'], 'lambda_function.lambda_handler')
        self.assertEqual(cognito_lambda['Timeout'], 900)  # 15 minutes
        self.assertEqual(cognito_lambda['MemorySize'], 512)
        
        # Verify environment variables are set
        env_vars = cognito_lambda['Environment']['Variables']
        self.assertIn('BACKUP_BUCKET_NAME', env_vars)
        self.assertIn('STAFF_USER_POOL_ID', env_vars)
        self.assertIn('PROVIDER_USER_POOL_ID', env_vars)

    def test_cognito_backup_eventbridge_rule_created(self):
        """Test that the EventBridge rule for daily Cognito backup is created."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack
        backup_infrastructure_stack = persistent_stack.backup_infrastructure_stack
        
        backup_stack_template = Template.from_stack(backup_infrastructure_stack)
        
        # Find EventBridge rules for Cognito backup
        cognito_backup_rules = backup_stack_template.find_resources(
            CfnRule.CFN_RESOURCE_TYPE_NAME,
            props=Match.object_like({
                'Properties': {
                    'ScheduleExpression': 'cron(0 2 * * ? *)',  # Daily at 2 AM UTC
                    'State': 'ENABLED'
                }
            })
        )
        
        self.assertGreaterEqual(len(cognito_backup_rules), 1, "Cognito backup EventBridge rule should be created")
        
        # Verify the rule targets the Lambda function
        rule = list(cognito_backup_rules.values())[0]
        targets = rule['Properties']['Targets']
        self.assertEqual(len(targets), 1)
        
        # Verify target points to the Cognito backup Lambda
        lambda_logical_id = backup_infrastructure_stack.get_logical_id(
            backup_infrastructure_stack.cognito_backup_lambda.node.default_child
        )
        target_arn = targets[0]['Arn']
        self.assertIn(lambda_logical_id, target_arn['Fn::GetAtt'][0])

    def test_cognito_backup_bucket_has_backup_plan(self):
        """Test that the Cognito backup bucket has a backup plan configured."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack
        backup_infrastructure_stack = persistent_stack.backup_infrastructure_stack
        
        backup_stack_template = Template.from_stack(backup_infrastructure_stack)
        
        # Find backup plans
        backup_plans = backup_stack_template.find_resources(CfnBackupPlan.CFN_RESOURCE_TYPE_NAME)
        
        # Should have multiple backup plans (DynamoDB tables + S3 bucket)
        self.assertGreaterEqual(len(backup_plans), 5, "Should have backup plans for tables and S3 bucket")
        
        # Find backup plan for Cognito backup bucket
        cognito_backup_plan = None
        for plan_id, plan in backup_plans.items():
            plan_name = plan['Properties']['BackupPlan']['BackupPlanName']
            if 'CognitoBackupBucket' in plan_name:
                cognito_backup_plan = plan
                break
        
        self.assertIsNotNone(cognito_backup_plan, "Cognito backup bucket should have a backup plan")
        
        # Verify backup plan configuration
        if cognito_backup_plan:
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

    def test_cognito_backup_bucket_backup_selection(self):
        """Test that the Cognito backup bucket has a backup selection configured."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack
        backup_infrastructure_stack = persistent_stack.backup_infrastructure_stack
        
        backup_stack_template = Template.from_stack(backup_infrastructure_stack)
        
        # Find backup selections
        backup_selections = backup_stack_template.find_resources(CfnBackupSelection.CFN_RESOURCE_TYPE_NAME)
        
        # Should have multiple backup selections (tables + S3 bucket)
        self.assertGreaterEqual(len(backup_selections), 5, "Should have backup selections for tables and S3 bucket")
        
        # Find backup selection for Cognito backup bucket
        cognito_backup_selection = None
        for selection_id, selection in backup_selections.items():
            selection_name = selection['Properties']['BackupSelection']['SelectionName']
            if 'CognitoBackupBucket' in selection_name:
                cognito_backup_selection = selection
                break
        
        self.assertIsNotNone(cognito_backup_selection, "Cognito backup bucket should have a backup selection")
        
        # Verify backup selection targets S3 resources
        if cognito_backup_selection:
            backup_selection_props = cognito_backup_selection['Properties']['BackupSelection']
            self.assertIn('Resources', backup_selection_props)
            resources = backup_selection_props['Resources']
            self.assertEqual(len(resources), 1)
            
            # Verify resource is an S3 bucket ARN
            resource_arn = resources[0]
            self.assertIn('s3', resource_arn)

    def test_cognito_backup_lambda_permissions(self):
        """Test that the Cognito backup Lambda has appropriate IAM permissions."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack
        backup_infrastructure_stack = persistent_stack.backup_infrastructure_stack
        
        backup_stack_template = Template.from_stack(backup_infrastructure_stack)
        
        # Find the Lambda's IAM role
        lambda_logical_id = backup_infrastructure_stack.get_logical_id(
            backup_infrastructure_stack.cognito_backup_lambda.node.default_child
        )
        
        cognito_lambda = self.get_resource_properties_by_logical_id(
            lambda_logical_id,
            backup_stack_template.find_resources(CfnFunction.CFN_RESOURCE_TYPE_NAME)
        )
        
        role_ref = cognito_lambda['Role']
        self.assertIn('Ref', role_ref)
        
        # Verify the Lambda has the required IAM policies
        from aws_cdk.aws_iam import CfnRole, CfnPolicy
        
        # Find the role and policies
        roles = backup_stack_template.find_resources(CfnRole.CFN_RESOURCE_TYPE_NAME)
        policies = backup_stack_template.find_resources(CfnPolicy.CFN_RESOURCE_TYPE_NAME)
        
        # Should have policies that grant Cognito and S3 permissions
        found_cognito_policy = False
        found_s3_policy = False
        
        for policy_id, policy in policies.items():
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
        
        self.assertTrue(found_cognito_policy, "Lambda should have Cognito permissions")
        self.assertTrue(found_s3_policy, "Lambda should have S3 permissions")

    def test_cognito_backup_alarm_created(self):
        """Test that CloudWatch alarm is created for Cognito backup failures."""
        persistent_stack = self.app.sandbox_backend_stage.persistent_stack
        backup_infrastructure_stack = persistent_stack.backup_infrastructure_stack
        
        backup_stack_template = Template.from_stack(backup_infrastructure_stack)
        
        # Find CloudWatch alarms
        from aws_cdk.aws_cloudwatch import CfnAlarm
        alarms = backup_stack_template.find_resources(CfnAlarm.CFN_RESOURCE_TYPE_NAME)
        
        # Find the Cognito backup failure alarm
        cognito_backup_alarm = None
        for alarm_id, alarm in alarms.items():
            alarm_desc = alarm['Properties'].get('AlarmDescription', '')
            if 'Cognito backup export Lambda has failed' in alarm_desc:
                cognito_backup_alarm = alarm
                break
        
        self.assertIsNotNone(cognito_backup_alarm, "Cognito backup failure alarm should be created")
        
        # Verify alarm configuration
        if cognito_backup_alarm:
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
        backup_infrastructure_stack = persistent_stack.backup_infrastructure_stack
        
        # Verify user pools are accessible
        self.assertTrue(hasattr(persistent_stack, 'staff_users'))
        self.assertTrue(hasattr(persistent_stack, 'provider_users_deprecated'))
        
        # Verify backup infrastructure has user pool IDs
        self.assertIsNotNone(backup_infrastructure_stack.staff_user_pool_id)
        self.assertIsNotNone(backup_infrastructure_stack.provider_user_pool_id)
        
        # Verify the IDs match the user pools
        self.assertEqual(
            backup_infrastructure_stack.staff_user_pool_id,
            persistent_stack.staff_users.user_pool_id
        )
        self.assertEqual(
            backup_infrastructure_stack.provider_user_pool_id,
            persistent_stack.provider_users_deprecated.user_pool_id
        )