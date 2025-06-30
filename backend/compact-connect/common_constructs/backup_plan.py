"""
Common backup construct for consistent backup policies across resources.

This construct provides a standardized way to implement AWS Backup plans for resources
with category-based configurations, schedule management, and cross-account replication.
"""

from aws_cdk import Duration
from aws_cdk.aws_backup import BackupPlan, BackupResource, BackupRule, BackupVault
from aws_cdk.aws_events import Schedule
from aws_cdk.aws_iam import Role
from aws_cdk.aws_s3 import IBucket
from constructs import Construct


class BackupPlanConstruct(Construct):
    """
    Common construct for implementing backup plans across different resource types.
    
    This construct creates backup plans with category-based configuration,
    supporting different backup policies for different resource types
    (critical_data, configuration_data, document_storage, etc.).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        resource_arn: str,
        backup_category: str,
        local_backup_vault: BackupVault,
        backup_service_role: Role,
        cross_account_vault_arn: str | None = None,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)
        
        # Get backup policy configuration from context
        backup_policies = scope.node.try_get_context('backup_policies') or {}
        category_policy = backup_policies.get(backup_category, self._get_default_policy(backup_category))
        
        # Create backup plan
        self.backup_plan = BackupPlan(
            self,
            'BackupPlan',
            backup_plan_name=f'{construct_id}-{backup_category}',
        )
        
        # Create backup rule with schedule and retention
        schedule_expression = category_policy.get('schedule', 'cron(0 2 * * ? *)')  # Default: daily at 2 AM UTC
        retention_days = category_policy.get('retention_days', 30)
        
        backup_rule = BackupRule(
            backup_vault=local_backup_vault,
            rule_name=f'{backup_category}-rule',
            schedule_expression=Schedule.expression(schedule_expression),
            delete_after=Duration.days(retention_days),
        )
        
        # Add cross-account copy if configured
        if cross_account_vault_arn and category_policy.get('cross_account_copy', True):
            backup_rule.copy_actions = [{
                'destination_backup_vault_arn': cross_account_vault_arn,
                'lifecycle': {
                    'delete_after': Duration.days(retention_days),
                },
            }]
        
        self.backup_plan.add_rule(backup_rule)
        
        # Add the resource to backup
        self.backup_plan.add_selection(
            'BackupSelection',
            resources=[BackupResource.from_arn(resource_arn)],
            role=backup_service_role,
        )
    
    def _get_default_policy(self, category: str) -> dict:
        """Get default backup policy for a category if not configured in context."""
        default_policies = {
            'document_storage': {
                'schedule': 'cron(0 2 * * ? *)',  # Daily at 2 AM UTC
                'retention_days': 90,
                'cross_account_copy': True,
            },
            'critical_data': {
                'schedule': 'cron(0 2 * * ? *)',  # Daily at 2 AM UTC
                'retention_days': 2555,  # 7 years
                'cross_account_copy': True,
            },
            'configuration_data': {
                'schedule': 'cron(0 2 * * ? *)',  # Daily at 2 AM UTC
                'retention_days': 1095,  # 3 years
                'cross_account_copy': True,
            },
        }
        return default_policies.get(category, {
            'schedule': 'cron(0 2 * * ? *)',
            'retention_days': 30,
            'cross_account_copy': True,
        })