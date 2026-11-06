from __future__ import annotations

import sys
from pathlib import Path

from aws_cdk import ArnFormat, Duration
from aws_cdk.aws_cloudwatch import Alarm, ComparisonOperator, TreatMissingData
from aws_cdk.aws_cloudwatch_actions import SnsAction
from aws_cdk.aws_events import EventPattern, Rule
from aws_cdk.aws_events_targets import LambdaFunction
from aws_cdk.aws_iam import Effect, PolicyStatement, Role, ServicePrincipal
from aws_cdk.aws_logs import FilterPattern, LogGroup, MetricFilter, RetentionDays
from aws_cdk.aws_scheduler import CfnScheduleGroup
from aws_cdk.aws_stepfunctions import (
    Choice,
    Condition,
    DefinitionBody,
    IntegrationPattern,
    JsonPath,
    LogLevel,
    LogOptions,
    Pass,
    Result,
    StateMachine,
    Succeed,
    TaskInput,
    Timeout,
)
from aws_cdk.aws_stepfunctions_tasks import LambdaInvoke
from cdk_nag import NagSuppressions
from common_constructs.python_function import PythonFunction
from common_constructs.stack import Stack
from constructs import Construct

_APP_ROOT = Path(__file__).resolve().parents[2]
_COMMON = _APP_ROOT / 'lambdas' / 'python' / 'common'
_COMMON_PYTHON = _APP_ROOT.parent / 'common-python'
for _path in (_COMMON_PYTHON, _COMMON):
    _path_text = str(_path)
    if _path.is_dir() and _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from cc_common.applicants.application_state import (  # noqa: E402
    ADMIN_OVERRIDE_TARGETS,
    STATE_DEFINITIONS,
    StateName,
    WorkflowAction,
)

from stacks import persistent_stack as ps  # noqa: E402

# App 09 creates this generation's expiry schedules in the group.
APPLICATION_SCHEDULE_GROUP_NAME = 'application-workflow'
_LAMBDA_RETRY_ERRORS = [
    'Lambda.ServiceException',
    'Lambda.AWSLambdaException',
    'Lambda.SdkClientException',
    'Lambda.TooManyRequestsException',
]
_WAIT_TIMEOUT = Duration.days(364).plus(Duration.hours(23))
_TASK_TIMEOUT = Duration.seconds(30)


class ApplicationWorkflow(Construct):
    """One standard workflow whose nodes come from ``STATE_DEFINITIONS``."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        persistent_stack: ps.PersistentStack,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)
        stack = Stack.of(self)
        self.schedule_group_name = APPLICATION_SCHEDULE_GROUP_NAME
        CfnScheduleGroup(self, 'ApplicationScheduleGroup', name=self.schedule_group_name)

        self._add_enter_state_function(stack, persistent_stack)
        self._add_state_machine(stack, persistent_stack)
        self._add_expiry_function(stack, persistent_stack)
        self._add_reconciler_function(stack, persistent_stack)
        self._add_scheduler_role(stack)
        self._add_execution_status_rule()
        self._add_workflow_metric_alarms(persistent_stack)

    def _add_enter_state_function(self, stack: Stack, persistent_stack: ps.PersistentStack) -> None:
        application_table = persistent_stack.application_table
        self.enter_state_function = PythonFunction(
            self,
            'EnterState',
            description='Records the application workflow state a Step Functions node has entered',
            lambda_dir='applicants-lambdas',
            index='enter_state.py',
            handler='enter_state',
            timeout=_TASK_TIMEOUT,
            environment={
                'APPLICATION_TABLE_NAME': application_table.table_name,
                'APPLICATION_STATUS_GSI_NAME': application_table.status_gsi_name,
                'APPLICATION_ACTOR_GSI_NAME': application_table.actor_gsi_name,
                'APPLICATION_APPLICANT_GSI_NAME': application_table.applicant_gsi_name,
                'APPLICATION_SCHEDULE_GROUP_NAME': self.schedule_group_name,
                **stack.common_env_vars,
            },
            alarm_topic=persistent_stack.alarm_topic,
        )
        application_table.grant_read_write_data(self.enter_state_function)
        persistent_stack.shared_encryption_key.grant_encrypt_decrypt(self.enter_state_function)
        self.enter_state_function.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['scheduler:DeleteSchedule'],
                resources=[self._schedule_arn(stack)],
            )
        )
        NagSuppressions.add_resource_suppressions_by_path(
            stack,
            f'{self.enter_state_function.role.node.path}/DefaultPolicy/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': """
                            This policy contains wild-carded actions and resources but they are scoped to the
                            application table, its encryption key, and this workflow's schedule group.
                            """,
                },
            ],
        )

    def _add_state_machine(self, stack: Stack, persistent_stack: ps.PersistentStack) -> None:
        entry_router = self._build_definition()
        log_group = LogGroup(
            self,
            'ApplicationWorkflowLogs',
            retention=RetentionDays.ONE_MONTH,
            encryption_key=persistent_stack.shared_encryption_key,
        )
        self.state_machine = StateMachine(
            self,
            'ApplicationStateMachine',
            definition_body=DefinitionBody.from_chainable(entry_router),
            timeout=Duration.days(365),
            tracing_enabled=True,
            logs=LogOptions(
                destination=log_group,
                level=LogLevel.ALL,
                include_execution_data=False,
            ),
        )
        self.enter_state_function.grant_invoke(self.state_machine)
        persistent_stack.shared_encryption_key.grant_encrypt_decrypt(self.state_machine)
        NagSuppressions.add_resource_suppressions_by_path(
            stack,
            f'{self.state_machine.node.path}/Role/DefaultPolicy/Resource',
            suppressions=[
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': """
                              This policy contains wild-carded actions and resources but they are scoped to the
                              EnterState function, its log group, and the shared encryption key.
                              """,
                },
            ],
        )
        self._add_execution_alarms(persistent_stack)

    def _build_definition(self) -> Choice:
        succeed = Succeed(self, 'WorkflowSucceeded', state_name='Succeed')
        nodes = {
            state_name: self._terminal_node(state_name)
            for state_name, definition in STATE_DEFINITIONS.items()
            if definition.terminal
        }
        for node in nodes.values():
            node.next(succeed)

        deactivate_on_timeout = self._reason_pass('DeactivateOnTimeout', 'TIMEOUT')
        deactivate_on_error = self._reason_pass('DeactivateOnError', 'WORKFLOW_ERROR')
        deactivate_on_timeout.next(nodes[StateName.DEACTIVATED])
        deactivate_on_error.next(nodes[StateName.DEACTIVATED])

        for state_name, definition in STATE_DEFINITIONS.items():
            if definition.terminal:
                continue
            nodes[state_name] = self._wait_node(state_name, deactivate_on_timeout, deactivate_on_error)

        admin_router = self._admin_router(nodes, deactivate_on_error)
        for state_name, definition in STATE_DEFINITIONS.items():
            if definition.terminal:
                continue
            nodes[state_name].next(
                self._action_choice(
                    state_name,
                    nodes=nodes,
                    admin_router=admin_router,
                    deactivate_on_error=deactivate_on_error,
                )
            )

        entry_router = Choice(self, 'EntryRouter', state_name='EntryRouter')
        entry_router.when(
            Condition.string_equals('$.startAt', StateName.STAFF_REVIEW.value),
            nodes[StateName.STAFF_REVIEW],
        )
        entry_router.otherwise(nodes[StateName.STARTED])
        return entry_router

    def _wait_node(self, state_name: StateName, deactivate_on_timeout: Pass, deactivate_on_error: Pass) -> LambdaInvoke:
        task = LambdaInvoke(
            self,
            state_name.value,
            state_name=state_name.value,
            lambda_function=self.enter_state_function,
            integration_pattern=IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            payload=self._enter_payload(state_name, mode='ENTER', include_token=True),
            result_path='$.transition',
            task_timeout=Timeout.duration(_WAIT_TIMEOUT),
            retry_on_service_exceptions=False,
        )
        self._add_lambda_retry(task)
        task.add_catch(deactivate_on_timeout, errors=['States.Timeout'], result_path='$.error')
        task.add_catch(deactivate_on_error, errors=['States.ALL'], result_path='$.error')
        return task

    def _terminal_node(self, state_name: StateName) -> LambdaInvoke:
        task = LambdaInvoke(
            self,
            state_name.value,
            state_name=state_name.value,
            lambda_function=self.enter_state_function,
            payload=self._enter_payload(state_name, mode='TERMINAL', include_token=False),
            task_timeout=Timeout.duration(_TASK_TIMEOUT),
            retry_on_service_exceptions=False,
        )
        self._add_lambda_retry(task)
        return task

    def _action_choice(
        self,
        state_name: StateName,
        *,
        nodes: dict[StateName, LambdaInvoke],
        admin_router: Choice,
        deactivate_on_error: Pass,
    ) -> Choice:
        choice = Choice(self, f'{state_name.value}Choice', state_name=f'{state_name.value}Choice')
        for action, target in STATE_DEFINITIONS[state_name].transitions.items():
            choice.when(Condition.string_equals('$.transition.action', action.value), nodes[target])
        choice.when(
            Condition.string_equals('$.transition.action', WorkflowAction.ADMIN_OVERRIDE.value),
            admin_router,
        )
        choice.when(
            Condition.string_equals('$.transition.action', WorkflowAction.ADMIN_DEACTIVATE.value),
            nodes[StateName.DEACTIVATED],
        )
        choice.otherwise(deactivate_on_error)
        return choice

    def _admin_router(self, nodes: dict[StateName, LambdaInvoke], deactivate_on_error: Pass) -> Choice:
        router = Choice(self, 'AdminRouter', state_name='AdminRouter')
        for target in sorted(ADMIN_OVERRIDE_TARGETS, key=lambda state: state.value):
            router.when(Condition.string_equals('$.transition.targetState', target.value), nodes[target])
        router.otherwise(deactivate_on_error)
        return router

    def _reason_pass(self, name: str, reason: str) -> Pass:
        return Pass(
            self,
            name,
            state_name=name,
            result=Result.from_string(reason),
            result_path='$.error.reason',
        )

    def _enter_payload(self, state_name: StateName, *, mode: str, include_token: bool) -> TaskInput:
        payload = {
            'compact': JsonPath.string_at('$.compact'),
            'applicationId': JsonPath.string_at('$.applicationId'),
            'generation': JsonPath.string_at('$.generation'),
            'mode': mode,
            'stateName': state_name.value,
            'executionArn': JsonPath.string_at('$$.Execution.Id'),
            'enteredTime': JsonPath.string_at('$$.State.EnteredTime'),
        }
        if include_token:
            payload['taskToken'] = JsonPath.task_token
        else:
            # The caught error carries TIMEOUT or WORKFLOW_ERROR. Admin deactivation is the
            # transition action, because that edge does not go through a reason Pass.
            payload['error'] = JsonPath.string_at('$.error')
            payload['transition'] = JsonPath.string_at('$.transition')
        return TaskInput.from_object(payload)

    @staticmethod
    def _add_lambda_retry(task: LambdaInvoke) -> None:
        task.add_retry(
            errors=_LAMBDA_RETRY_ERRORS,
            interval=Duration.seconds(2),
            backoff_rate=2,
            max_attempts=2,
        )

    def _add_execution_alarms(self, persistent_stack: ps.PersistentStack) -> None:
        alarm_action = SnsAction(persistent_stack.alarm_topic)
        for name, metric in (
            ('ExecutionFailed', self.state_machine.metric_failed()),
            ('ExecutionTimedOut', self.state_machine.metric_timed_out()),
            ('ExecutionAborted', self.state_machine.metric_aborted()),
        ):
            Alarm(
                self,
                f'{name}Alarm',
                metric=metric,
                evaluation_periods=1,
                threshold=1,
                actions_enabled=True,
                alarm_description=f'{self.state_machine.node.path} execution {name}',
                comparison_operator=ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=TreatMissingData.NOT_BREACHING,
            ).add_alarm_action(alarm_action)

    def _add_expiry_function(self, stack: Stack, persistent_stack: ps.PersistentStack) -> None:
        application_table = persistent_stack.application_table
        self.expiry_function = PythonFunction(
            self,
            'ExpiryDeactivation',
            description='Deactivates an application when its one-time expiry schedule fires',
            lambda_dir='applicants-lambdas',
            index='expiry_deactivation.py',
            handler='expiry_deactivation',
            timeout=_TASK_TIMEOUT,
            environment={
                **self._application_environment(stack, application_table),
                'APPLICATION_STATE_MACHINE_ARN': self.state_machine.state_machine_arn,
            },
            alarm_topic=persistent_stack.alarm_topic,
        )
        application_table.grant_read_write_data(self.expiry_function)
        persistent_stack.shared_encryption_key.grant_encrypt_decrypt(self.expiry_function)
        self.expiry_function.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['states:SendTaskSuccess'],
                resources=['*'],
            )
        )
        self.expiry_function.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['states:DescribeExecution'],
                resources=[self._execution_arn(stack)],
            )
        )
        self._suppress_role_wildcard(
            stack,
            self.expiry_function.role,
            """
            This policy contains wild-carded actions and resources but they are scoped to the
            application table, its encryption key, and this workflow's executions.
            SendTaskSuccess does not support a resource-level permission.
            """,
        )

    def _add_reconciler_function(self, stack: Stack, persistent_stack: ps.PersistentStack) -> None:
        application_table = persistent_stack.application_table
        self.reconciler_function = PythonFunction(
            self,
            'ExecutionStatusReconciler',
            description='Records an application execution that failed, timed out, or was aborted',
            lambda_dir='applicants-lambdas',
            index='execution_status_reconciler.py',
            handler='execution_status_reconciler',
            timeout=_TASK_TIMEOUT,
            environment={
                **self._application_environment(stack, application_table),
                'APPLICATION_STATE_MACHINE_ARN': self.state_machine.state_machine_arn,
            },
            alarm_topic=persistent_stack.alarm_topic,
        )
        application_table.grant_read_write_data(self.reconciler_function)
        persistent_stack.shared_encryption_key.grant_encrypt_decrypt(self.reconciler_function)
        self.reconciler_function.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['scheduler:DeleteSchedule'],
                resources=[self._schedule_arn(stack)],
            )
        )
        self._suppress_role_wildcard(
            stack,
            self.reconciler_function.role,
            """
            This policy contains wild-carded actions and resources but they are scoped to the
            application table, its encryption key, and this workflow's schedule group.
            """,
        )

    def _add_scheduler_role(self, stack: Stack) -> None:
        self.scheduler_role = Role(
            self,
            'ExpirySchedulerRole',
            assumed_by=ServicePrincipal('scheduler.amazonaws.com'),
            description='Allows the application expiry schedule to invoke its deactivation function',
        )
        self.expiry_function.grant_invoke(self.scheduler_role)
        self.scheduler_role_arn = self.scheduler_role.role_arn
        self._suppress_role_wildcard(
            stack,
            self.scheduler_role,
            """
            This role can invoke only the application expiry function. The invoke grant includes
            the function's log and qualifier resources.
            """,
        )

    def _add_execution_status_rule(self) -> None:
        Rule(
            self,
            'ExecutionStatusRule',
            description='Reconcile an application when its workflow execution stops unexpectedly',
            event_pattern=EventPattern(
                source=['aws.states'],
                detail_type=['Step Functions Execution Status Change'],
                detail={
                    'status': ['FAILED', 'TIMED_OUT', 'ABORTED'],
                    'stateMachineArn': [self.state_machine.state_machine_arn],
                },
            ),
            targets=[LambdaFunction(self.reconciler_function)],
        )

    def _add_workflow_metric_alarms(self, persistent_stack: ps.PersistentStack) -> None:
        alarm_action = SnsAction(persistent_stack.alarm_topic)
        for metric_name, log_group in (
            ('ApplicationExpiryDeactivationFailed', self.expiry_function.log_group),
            ('ApplicationCallbackDeliveryExhausted', self.expiry_function.log_group),
            ('ApplicationExecutionBroken', self.reconciler_function.log_group),
            ('ApplicationReopenForcedStop', self.reconciler_function.log_group),
        ):
            metric_filter = MetricFilter(
                self,
                f'{metric_name}Filter',
                log_group=log_group,
                metric_namespace='compact-connect',
                metric_name=metric_name,
                filter_pattern=FilterPattern.literal(f'{{ $.{metric_name} = 1 }}'),
                metric_value='1',
            )
            Alarm(
                self,
                f'{metric_name}Alarm',
                metric=metric_filter.metric(statistic='Sum', period=Duration.minutes(5)),
                evaluation_periods=1,
                threshold=1,
                actions_enabled=True,
                alarm_description=metric_name,
                comparison_operator=ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=TreatMissingData.NOT_BREACHING,
            ).add_alarm_action(alarm_action)
        Alarm(
            self,
            'ReconcilerErrorsAlarm',
            metric=self.reconciler_function.metric_errors(period=Duration.minutes(5)),
            evaluation_periods=1,
            threshold=1,
            actions_enabled=True,
            alarm_description='Application reconciler errors',
            comparison_operator=ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(alarm_action)

    def _application_environment(self, stack: Stack, application_table) -> dict:
        return {
            'APPLICATION_TABLE_NAME': application_table.table_name,
            'APPLICATION_STATUS_GSI_NAME': application_table.status_gsi_name,
            'APPLICATION_ACTOR_GSI_NAME': application_table.actor_gsi_name,
            'APPLICATION_APPLICANT_GSI_NAME': application_table.applicant_gsi_name,
            'APPLICATION_SCHEDULE_GROUP_NAME': self.schedule_group_name,
            **stack.common_env_vars,
        }

    def _execution_arn(self, stack: Stack) -> str:
        return stack.format_arn(
            service='states',
            resource='execution',
            resource_name=f'{self.state_machine.state_machine_name}:*',
            arn_format=ArnFormat.COLON_RESOURCE_NAME,
        )

    def _suppress_role_wildcard(self, stack: Stack, role, reason: str) -> None:
        NagSuppressions.add_resource_suppressions_by_path(
            stack,
            f'{role.node.path}/DefaultPolicy/Resource',
            suppressions=[{'id': 'AwsSolutions-IAM5', 'reason': reason}],
        )

    def _schedule_arn(self, stack: Stack) -> str:
        return stack.format_arn(
            service='scheduler',
            resource='schedule',
            resource_name=f'{self.schedule_group_name}/*',
            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
        )
