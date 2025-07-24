"""Test that CCBackupPlan handles optional backup_policy correctly"""

import unittest
from aws_cdk import App, Stack
from aws_cdk.aws_backup import BackupResource
from aws_cdk.aws_dynamodb import Table, Attribute, AttributeType

from common_constructs.backup_plan import CCBackupPlan


class TestCCBackupPlanOptionalPolicy(unittest.TestCase):
    def setUp(self):
        self.app = App()
        self.stack = Stack(self.app, "TestStack")
        
        # Create a mock table for backup resources
        self.test_table = Table(
            self.stack,
            "TestTable",
            table_name="test-table",
            partition_key=Attribute(name="id", type=AttributeType.STRING),
        )

    def test_backup_plan_with_none_policy(self):
        """Test that CCBackupPlan gracefully handles None backup_policy"""
        backup_plan = CCBackupPlan(
            self.stack,
            "TestBackupPlan",
            backup_plan_name_prefix="test",
            backup_resources=[BackupResource.from_dynamo_db_table(self.test_table)],
            backup_vault=None,  # This will trigger the disabled backup path
            backup_service_role=None,
            cross_account_backup_vault=None,
            backup_policy=None,  # This should not cause any errors
        )
        
        # When backup is disabled, both plan and selection should be None
        self.assertIsNone(backup_plan.backup_plan)
        self.assertIsNone(backup_plan.backup_selection)

    def test_backup_plan_with_none_vault_but_valid_policy(self):
        """Test that CCBackupPlan gracefully handles None vault even with valid policy"""
        backup_policy = {
            'schedule': {'hour': '5', 'minute': '0'},
            'delete_after_days': 30,
            'cold_storage_after_days': 7
        }
        
        backup_plan = CCBackupPlan(
            self.stack,
            "TestBackupPlan2",
            backup_plan_name_prefix="test2",
            backup_resources=[BackupResource.from_dynamo_db_table(self.test_table)],
            backup_vault=None,  # This will trigger the disabled backup path
            backup_service_role=None,
            cross_account_backup_vault=None,
            backup_policy=backup_policy,  # Valid policy but backup infrastructure disabled
        )
        
        # When backup infrastructure is disabled, both plan and selection should be None
        # even if backup_policy is provided
        self.assertIsNone(backup_plan.backup_plan)
        self.assertIsNone(backup_plan.backup_selection)

    def test_construct_can_be_created_successfully(self):
        """Test that the construct can be created without throwing exceptions"""
        try:
            CCBackupPlan(
                self.stack,
                "TestBackupPlan3",
                backup_plan_name_prefix="test3",
                backup_resources=[BackupResource.from_dynamo_db_table(self.test_table)],
                backup_vault=None,
                backup_service_role=None,
                cross_account_backup_vault=None,
                backup_policy=None,
            )
        except Exception as e:
            self.fail(f"CCBackupPlan constructor raised an exception: {e}")
