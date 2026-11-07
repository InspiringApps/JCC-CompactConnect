from __future__ import annotations

from aws_cdk import ArnFormat, Duration, Stack
from aws_cdk.aws_iam import Effect, PolicyStatement
from cdk_nag import NagSuppressions
from common_constructs.python_function import PythonFunction
from constructs import Construct

from stacks import api_lambda_stack as als
from stacks import persistent_stack as ps
from stacks.application_workflow_stack import ApplicationWorkflowStack


class ApplicationsLambdas:
    def __init__(
        self,
        *,
        scope: Construct,
        persistent_stack: ps.PersistentStack,
        application_workflow_stack: ApplicationWorkflowStack,
        api_lambda_stack: als.ApiLambdaStack,
    ):
        super().__init__()
        stack = Stack.of(scope)
        application_table = persistent_stack.application_table
        self.applicant_applications_handler = PythonFunction(
            scope,
            'ApplicantApplicationsFunction',
            description='Practitioner application create, read, section patch, submit, and resubmit',
            index='applicant_applications.py',
            lambda_dir='applicants-lambdas',
            handler='applicant_applications',
            timeout=Duration.seconds(30),
            environment={
                'APPLICATION_TABLE_NAME': application_table.table_name,
                'APPLICATION_STATUS_GSI_NAME': application_table.status_gsi_name,
                'APPLICATION_ACTOR_GSI_NAME': application_table.actor_gsi_name,
                'APPLICATION_APPLICANT_GSI_NAME': application_table.applicant_gsi_name,
                'APPLICATION_STATE_MACHINE_ARN': application_workflow_stack.state_machine.state_machine_arn,
                'APPLICATION_SCHEDULE_GROUP_NAME': application_workflow_stack.schedule_group_name,
                'APPLICATION_EXPIRY_FUNCTION_ARN': application_workflow_stack.expiry_function.function_arn,
                'APPLICATION_SCHEDULER_ROLE_ARN': application_workflow_stack.scheduler_role_arn,
                **stack.common_env_vars,
            },
        )
        application_table.grant_read_write_data(self.applicant_applications_handler)
        persistent_stack.shared_encryption_key.grant_encrypt_decrypt(self.applicant_applications_handler)
        self.applicant_applications_handler.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['states:StartExecution'],
                resources=[application_workflow_stack.state_machine.state_machine_arn],
            )
        )
        self.applicant_applications_handler.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['states:SendTaskSuccess'],
                resources=['*'],
            )
        )
        # An ambiguous StartExecution is resolved by describing the execution.
        self.applicant_applications_handler.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['states:DescribeExecution'],
                resources=[_execution_arn(stack, application_workflow_stack)],
            )
        )
        self.applicant_applications_handler.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['scheduler:CreateSchedule'],
                resources=[_schedule_arn(stack, application_workflow_stack)],
            )
        )
        self.applicant_applications_handler.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['iam:PassRole'],
                resources=[application_workflow_stack.scheduler_role_arn],
                conditions={'StringEquals': {'iam:PassedToService': 'scheduler.amazonaws.com'}},
            )
        )
        NagSuppressions.add_resource_suppressions_by_path(
            stack,
            path=f'{self.applicant_applications_handler.role.node.path}/DefaultPolicy/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': """
                    This policy is scoped to the application table, its encryption key, this workflow's
                    state machine, and its schedule group. SendTaskSuccess does not support a
                    resource-level permission. The schedule resource name ends in the group wildcard
                    because each application creates its own schedule.
                    """,
                },
            ],
        )
        api_lambda_stack.log_groups.append(self.applicant_applications_handler.log_group)


def _execution_arn(stack: Stack, workflow: ApplicationWorkflowStack) -> str:
    return stack.format_arn(
        service='states',
        resource='execution',
        resource_name=f'{workflow.state_machine.state_machine_name}:*',
        arn_format=ArnFormat.COLON_RESOURCE_NAME,
    )


def _schedule_arn(stack: Stack, workflow: ApplicationWorkflowStack) -> str:
    return stack.format_arn(
        service='scheduler',
        resource='schedule',
        resource_name=f'{workflow.schedule_group_name}/*',
        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
    )
