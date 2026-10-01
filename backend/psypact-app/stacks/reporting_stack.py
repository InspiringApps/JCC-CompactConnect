from __future__ import annotations

import json
import os

from aws_cdk import Duration
from aws_cdk.aws_cloudwatch import Alarm, ComparisonOperator, Stats, TreatMissingData
from aws_cdk.aws_cloudwatch_actions import SnsAction
from aws_cdk.aws_events import Rule, RuleTargetInput, Schedule
from aws_cdk.aws_events_targets import LambdaFunction
from aws_cdk.aws_lambda import Runtime
from aws_cdk.aws_logs import QueryDefinition, QueryString
from cdk_nag import NagSuppressions
from common_constructs.python_function import PythonFunction
from common_constructs.stack import AppStack
from constructs import Construct

from stacks import persistent_stack as ps


class ReportingStack(AppStack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment_name: str,
        persistent_stack: ps.PersistentStack,
        **kwargs,
    ):
        super().__init__(scope, construct_id, environment_name=environment_name, **kwargs)
        self._add_transaction_reporting_chain(persistent_stack)

    def _add_transaction_reporting_chain(self, persistent_stack: ps.PersistentStack):
        """Add the transaction reporting lambda and event rules."""
        self.transaction_reporter = PythonFunction(
            self,
            'TransactionReporter',
            description='Transaction report generator',
            handler='generate_transaction_reports',
            runtime=Runtime.PYTHON_3_12,
            lambda_dir='purchases',
            shared=True,
            index=os.path.join('handlers', 'transaction_reporting.py'),
            timeout=Duration.minutes(15),
            # This lambda sends email notifications, so we do not want it to retry in the event of a failure
            # we will instead trigger an alert for support to investigate and address as needed.
            retry_attempts=0,
            # Setting this memory size higher than others because it can potentially pull in a lot of data from
            # DynamoDB, and we want to ensure it has enough memory to handle that.
            memory_size=3008,
            environment={
                'TRANSACTION_HISTORY_TABLE_NAME': persistent_stack.transaction_history_table.table_name,
                'TRANSACTION_REPORTS_BUCKET_NAME': persistent_stack.transaction_reports_bucket.bucket_name,
                'PROVIDER_TABLE_NAME': persistent_stack.provider_table.table_name,
                'COMPACT_CONFIGURATION_TABLE_NAME': persistent_stack.compact_configuration_table.table_name,
                'EMAIL_NOTIFICATION_SERVICE_LAMBDA_NAME': persistent_stack.email_notification_service_lambda.function_name,  # noqa: E501 line-too-long
                **self.common_env_vars,
            },
        )
        NagSuppressions.add_resource_suppressions(
            self.transaction_reporter,
            suppressions=[
                {
                    'id': 'AwsSolutions-L1',
                    'reason': 'Our Authorize.Net dependency is not yet compatible with Python 3.13',
                },
            ],
        )

        # Grant necessary permissions
        persistent_stack.transaction_history_table.grant_read_data(self.transaction_reporter)
        persistent_stack.provider_table.grant_read_data(self.transaction_reporter)
        persistent_stack.compact_configuration_table.grant_read_data(self.transaction_reporter)
        persistent_stack.email_notification_service_lambda.grant_invoke(self.transaction_reporter)
        persistent_stack.transaction_reports_bucket.grant_read_write(self.transaction_reporter)

        NagSuppressions.add_resource_suppressions_by_path(
            self,
            f'{self.transaction_reporter.role.node.path}/DefaultPolicy/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': """
                            This policy contains wild-carded actions and resources but they are scoped to the
                            specific actions, KMS key, reporting bucket, and Tables that this lambda specifically
                            needs access to.
                            """,
                },
            ],
        )

        # Create event rules for each compact
        for compact in json.loads(self.common_env_vars['COMPACTS']):
            Rule(
                self,
                f'{compact.capitalize()}-WeeklyTransactionReportRule',
                # Send weekly reports every Monday at 4:00 AM UTC (Sunday 11 PM EST)
                # this gives the transaction collection process several days
                # to ensure we've collected all transactions from authorize.net
                # for the previous week, even if authorize.net settles batches late.
                schedule=Schedule.cron(week_day='MON', hour='4', minute='0', month='*', year='*'),
                targets=[
                    LambdaFunction(
                        handler=self.transaction_reporter,
                        event=RuleTargetInput.from_object({'compact': compact.lower(), 'reportingCycle': 'weekly'}),
                    )
                ],
            )

            # Monthly reports run every month on the first day of the month several hours after the
            # daily transaction collection process has run.
            # This helps ensure that our time range is the full month
            Rule(
                self,
                f'{compact.capitalize()}-MonthlyTransactionReportRule',
                schedule=Schedule.cron(day='3', hour='2', minute='0', month='*', year='*'),
                targets=[
                    LambdaFunction(
                        handler=self.transaction_reporter,
                        event=RuleTargetInput.from_object({'compact': compact.lower(), 'reportingCycle': 'monthly'}),
                    )
                ],
            )

        # Add alarms
        Alarm(
            self,
            'TransactionReporterFailure',
            metric=self.transaction_reporter.metric_errors(statistic=Stats.SUM),
            evaluation_periods=1,
            threshold=1,
            actions_enabled=True,
            alarm_description=f'{self.transaction_reporter.node.path} failed to process an event',
            comparison_operator=ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(SnsAction(persistent_stack.alarm_topic))

        # If the max function execution time is approaching its max timeout
        Alarm(
            self,
            'TransactionReporterDurationAlarm',
            metric=self.transaction_reporter.metric_duration(statistic=Stats.MAXIMUM, period=Duration.days(1)),
            evaluation_periods=1,
            threshold=600_000,  # 10 minutes
            actions_enabled=True,
            alarm_description=f'{self.transaction_reporter.node.path} Lambda Duration',
            comparison_operator=ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(SnsAction(persistent_stack.alarm_topic))

        QueryDefinition(
            self,
            'TransactionReporterQuery',
            query_definition_name=f'{self.node.id}/TransactionReporter',
            query_string=QueryString(
                fields=['@timestamp', '@log', 'level', 'message', 'compact', '@message'],
                filter_statements=['level in ["INFO", "WARNING", "ERROR"]'],
                sort='@timestamp desc',
            ),
            log_groups=[self.transaction_reporter.log_group],
        )
