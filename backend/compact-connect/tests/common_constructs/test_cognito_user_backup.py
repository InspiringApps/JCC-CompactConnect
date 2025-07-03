"""
Test suite for the CognitoUserBackup common construct.

This module tests the CognitoUserBackup construct to ensure it creates all necessary
resources with proper configuration, including the S3 bucket, Lambda function,
EventBridge rule, CloudWatch alarm, and backup plan.
"""
import json
from unittest import TestCase

from aws_cdk import App, Duration, RemovalPolicy, Stack
from aws_cdk.assertions import Match, Template
from aws_cdk.aws_backup import CfnBackupPlan, CfnBackupSelection, CfnBackupVault
from aws_cdk.aws_cloudwatch import CfnAlarm
from aws_cdk.aws_events import CfnRule
from aws_cdk.aws_iam import CfnPolicy, CfnRole
from aws_cdk.aws_kms import Key
from aws_cdk.aws_lambda import CfnFunction
from aws_cdk.aws_s3 import CfnBucket
from aws_cdk.aws_sns import Topic

from common_constructs.access_logs_bucket import AccessLogsBucket
from common_constructs.cognito_user_backup import CognitoUserBackup
from stacks.backup_infrastructure_stack import BackupInfrastructureStack


class TestCognitoUserBackup(TestCase):
    def setUp(self):
        """Set up test infrastructure."""
        self.app = App()
        self.stack = Stack(self.app, 'TestStack')
        
        # Create required dependencies
        self.encryption_key = Key(self.stack, 'TestKey')
        self.alarm_topic = Topic(self.stack, 'AlarmTopic', master_key=self.encryption_key)
        self.access_logs_bucket = AccessLogsBucket(
            self.stack, 'AccessLogsBucket', 
            encryption_key=self.encryption_key,
            removal_policy=RemovalPolicy.DESTROY
        )
        
        # Create backup infrastructure stack for dependencies
        self.backup_infrastructure_stack = BackupInfrastructureStack(
            self.stack, 'BackupInfrastructure',
            encryption_key=self.encryption_key,
            removal_policy=RemovalPolicy.DESTROY
        )
        
        # Test environment context
        self.environment_context = {
            'backup_policies': {
                'export_data': {
                    'backup_vault_name': 'test-vault',
                    'delete_after_days': 365,
                    'transition_to_cold_storage_after_days': 30,
                    'schedule': 'cron(0 2 * * ? *)'
                }
            }
        }
        
        # Create the construct under test
        self.cognito_backup = CognitoUserBackup(
            self.stack,
            'TestCognitoBackup',
            user_pool_id='us-east-1_TestPool123',
            access_logs_bucket=self.access_logs_bucket,
            encryption_key=self.encryption_key,
            removal_policy=RemovalPolicy.DESTROY,
            backup_infrastructure_stack=self.backup_infrastructure_stack,
            environment_context=self.environment_context,
            alarm_topic=self.alarm_topic,
        )
        
        self.template = Template.from_stack(self.stack)

    def test_creates_s3_backup_bucket(self):
        """Test that the S3 backup bucket is created with proper configuration."""
        # Should create an S3 bucket with KMS encryption
        self.template.has_resource_properties(
            CfnBucket.CFN_RESOURCE_TYPE_NAME,
            {
                'BucketEncryption': {
                    'ServerSideEncryptionConfiguration': [
                        {
                            'ServerSideEncryptionByDefault': {
                                'SSEAlgorithm': 'aws:kms',
                                'KMSMasterKeyID': {
                                    'Fn::GetAtt': [
                                        self.stack.get_logical_id(self.encryption_key.node.default_child),
                                        'Arn'
                                    ]
                                }
                            }
                        }
                    ]
                },
                'LoggingConfiguration': {
                    'DestinationBucketName': {
                        'Ref': self.stack.get_logical_id(self.access_logs_bucket.node.default_child)
                    }
                },
                'PublicAccessBlockConfiguration': {
                    'BlockPublicAcls': True,
                    'BlockPublicPolicy': True,
                    'IgnorePublicAcls': True,
                    'RestrictPublicBuckets': True,
                }
            }
        )

    def test_creates_lambda_function(self):
        """Test that the Lambda function is created with proper configuration."""
        # Find the Lambda function
        lambda_functions = self.template.find_resources(
            CfnFunction.CFN_RESOURCE_TYPE_NAME,
            {
                'Properties': {
                    'Handler': 'handlers.cognito_backup.backup_handler',
                    'Description': 'Export user pool data for backup purposes',
                }
            }
        )
        self.assertEqual(len(lambda_functions), 1, "Should have exactly one Cognito backup Lambda function")
        
        lambda_logical_id = list(lambda_functions.keys())[0]
        lambda_props = lambda_functions[lambda_logical_id]['Properties']
        
        # Verify function configuration
        self.assertEqual(lambda_props['Runtime'], 'python3.12')
        self.assertEqual(lambda_props['Timeout'], 900)  # 15 minutes
        self.assertEqual(lambda_props['MemorySize'], 512)
        
        # Verify environment variables
        env_vars = lambda_props['Environment']['Variables']
        self.assertIn('BACKUP_BUCKET_NAME', env_vars)
        self.assertIn('USER_POOL_ID', env_vars)
        self.assertEqual(env_vars['USER_POOL_ID'], 'us-east-1_TestPool123')

    def test_creates_iam_permissions_for_lambda(self):
        """Test that the Lambda function has proper IAM permissions."""
        # Should have policies for Cognito access
        cognito_policies = self.template.find_resources(
            CfnPolicy.CFN_RESOURCE_TYPE_NAME,
            {
                'Properties': {
                    'PolicyDocument': {
                        'Statement': Match.array_with([
                            Match.object_like({
                                'Effect': 'Allow',
                                'Action': [
                                    'cognito-idp:ListUsers',
                                    'cognito-idp:DescribeUserPool'
                                ],
                                'Resource': 'arn:aws:cognito-idp:*:*:userpool/us-east-1_TestPool123'
                            })
                        ])
                    }
                }
            }
        )
        self.assertGreaterEqual(len(cognito_policies), 1, "Should have IAM policy for Cognito access")

        # Should have policies for S3 access
        s3_policies = self.template.find_resources(
            CfnPolicy.CFN_RESOURCE_TYPE_NAME,
            {
                'Properties': {
                    'PolicyDocument': {
                        'Statement': Match.array_with([
                            Match.object_like({
                                'Effect': 'Allow',
                                'Action': Match.any_value(),
                                'Resource': Match.any_value()
                            })
                        ])
                    }
                }
            }
        )
        # Should have at least one policy with S3 actions
        found_s3_policy = False
        for policy_id, policy in s3_policies.items():
            for statement in policy['Properties']['PolicyDocument']['Statement']:
                if any('s3:' in action for action in statement.get('Action', [])):
                    found_s3_policy = True
                    break
            if found_s3_policy:
                break
        self.assertTrue(found_s3_policy, "Should have IAM policy for S3 access")

    def test_creates_eventbridge_rule(self):
        """Test that the EventBridge rule is created for daily scheduling."""
        # Find EventBridge rules
        rules = self.template.find_resources(
            CfnRule.CFN_RESOURCE_TYPE_NAME,
            {
                'Properties': {
                    'Description': 'Daily schedule for user pool backup export',
                    'ScheduleExpression': 'cron(0 2 * * ? *)',  # 2 AM UTC daily
                    'State': 'ENABLED'
                }
            }
        )
        self.assertEqual(len(rules), 1, "Should have exactly one EventBridge rule")
        
        rule_props = list(rules.values())[0]['Properties']
        
        # Verify the rule targets the Lambda function
        self.assertIn('Targets', rule_props)
        targets = rule_props['Targets']
        self.assertEqual(len(targets), 1, "Rule should have exactly one target")
        
        target = targets[0]
        self.assertIn('Arn', target)
        self.assertIn('Input', target)
        
        # Verify the input contains required parameters
        input_json = json.loads(target['Input'])
        self.assertEqual(input_json['user_pool_id'], 'us-east-1_TestPool123')
        self.assertIn('backup_bucket_name', input_json)

    def test_creates_cloudwatch_alarm(self):
        """Test that the CloudWatch alarm is created with proper configuration."""
        alarm_topic_logical_id = self.stack.get_logical_id(self.alarm_topic.node.default_child)
        
        # Find CloudWatch alarms
        alarms = self.template.find_resources(
            CfnAlarm.CFN_RESOURCE_TYPE_NAME,
            {
                'Properties': {
                    'AlarmDescription': 'User pool backup export Lambda has failed. User data backup may be incomplete.',
                    'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                    'Threshold': 1,
                    'EvaluationPeriods': 1,
                    'TreatMissingData': 'notBreaching'
                }
            }
        )
        self.assertEqual(len(alarms), 1, "Should have exactly one CloudWatch alarm")
        
        alarm_props = list(alarms.values())[0]['Properties']
        
        # Verify the alarm targets the SNS topic
        self.assertIn('AlarmActions', alarm_props)
        alarm_actions = alarm_props['AlarmActions']
        self.assertEqual(len(alarm_actions), 1, "Alarm should have exactly one action")
        self.assertEqual(alarm_actions[0]['Ref'], alarm_topic_logical_id)
        
        # Verify metric configuration
        self.assertEqual(alarm_props['Namespace'], 'AWS/Lambda')
        self.assertEqual(alarm_props['MetricName'], 'Errors')

    def test_creates_backup_plan(self):
        """Test that the backup plan is created for the bucket."""
        # Should create a backup plan
        backup_plans = self.template.find_resources(
            CfnBackupPlan.CFN_RESOURCE_TYPE_NAME,
            {
                'Properties': {
                    'BackupPlan': {
                        'BackupPlanName': Match.string_like_regexp('.*-cognito-backup')
                    }
                }
            }
        )
        self.assertGreaterEqual(len(backup_plans), 1, "Should have at least one backup plan")

        # Should create a backup selection
        backup_selections = self.template.find_resources(
            CfnBackupSelection.CFN_RESOURCE_TYPE_NAME,
            {
                'Properties': {
                    'BackupSelection': {
                        'SelectionName': Match.any_value(),
                        'IamRoleArn': Match.any_value(),
                        'Resources': Match.array_with([
                            Match.string_like_regexp('.*')
                        ])
                    }
                }
            }
        )
        self.assertGreaterEqual(len(backup_selections), 1, "Should have at least one backup selection")

    def test_alarm_topic_is_required(self):
        """Test that alarm_topic is a required parameter."""
        with self.assertRaises(TypeError):
            CognitoUserBackup(
                self.stack,
                'TestCognitoBackupNoAlarm',
                user_pool_id='us-east-1_TestPool123',
                access_logs_bucket=self.access_logs_bucket,
                encryption_key=self.encryption_key,
                removal_policy=RemovalPolicy.DESTROY,
                backup_infrastructure_stack=self.backup_infrastructure_stack,
                environment_context=self.environment_context,
                # alarm_topic is missing - should raise TypeError
            )

    def test_construct_properties(self):
        """Test that the construct exposes expected properties."""
        # Verify that the construct exposes key properties
        self.assertIsNotNone(self.cognito_backup.backup_bucket)
        self.assertIsNotNone(self.cognito_backup.export_lambda)
        self.assertIsNotNone(self.cognito_backup.backup_rule)
        self.assertIsNotNone(self.cognito_backup.failure_alarm)
        self.assertEqual(self.cognito_backup.user_pool_id, 'us-east-1_TestPool123')
        self.assertEqual(self.cognito_backup.encryption_key, self.encryption_key)

    def test_multiple_instances_unique_resources(self):
        """Test that multiple instances create unique resources."""
        # Create a second instance
        cognito_backup_2 = CognitoUserBackup(
            self.stack,
            'TestCognitoBackup2',
            user_pool_id='us-east-1_TestPool456',
            access_logs_bucket=self.access_logs_bucket,
            encryption_key=self.encryption_key,
            removal_policy=RemovalPolicy.DESTROY,
            backup_infrastructure_stack=self.backup_infrastructure_stack,
            environment_context=self.environment_context,
            alarm_topic=self.alarm_topic,
        )
        
        template = Template.from_stack(self.stack)
        
        # Should have 2 Lambda functions
        lambda_functions = template.find_resources(
            CfnFunction.CFN_RESOURCE_TYPE_NAME,
            {
                'Properties': {
                    'Handler': 'handlers.cognito_backup.backup_handler',
                    'Description': 'Export user pool data for backup purposes',
                }
            }
        )
        self.assertEqual(len(lambda_functions), 2, "Should have two Lambda functions for two constructs")
        
        # Should have 2 S3 buckets (plus access logs bucket)
        buckets = template.find_resources(CfnBucket.CFN_RESOURCE_TYPE_NAME)
        self.assertGreaterEqual(len(buckets), 3, "Should have at least 3 buckets (2 backup + 1 access logs)")
        
        # Should have 2 CloudWatch alarms
        alarms = template.find_resources(
            CfnAlarm.CFN_RESOURCE_TYPE_NAME,
            {
                'Properties': {
                    'AlarmDescription': 'User pool backup export Lambda has failed. User data backup may be incomplete.',
                }
            }
        )
        self.assertEqual(len(alarms), 2, "Should have two CloudWatch alarms for two constructs")