import json
import sys
from pathlib import Path
from unittest import TestCase

_APP_ROOT = Path(__file__).resolve().parents[2]
for _path in (_APP_ROOT.parent / 'common-python', _APP_ROOT / 'lambdas' / 'python' / 'common'):
    _path_text = str(_path)
    if _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from aws_cdk.assertions import Template  # noqa: E402
from aws_cdk.aws_logs import CfnLogGroup  # noqa: E402
from cc_common.applicants.application_state import (  # noqa: E402
    ADMIN_OVERRIDE_TARGETS,
    STATE_DEFINITIONS,
    StateName,
    WorkflowAction,
)

from tests.app.base import TstAppABC  # noqa: E402

_LAMBDA_RETRY_ERRORS = [
    'Lambda.ServiceException',
    'Lambda.AWSLambdaException',
    'Lambda.SdkClientException',
    'Lambda.TooManyRequestsException',
]
_WAIT_TIMEOUT_SECONDS = (364 * 24 * 60 * 60) + (23 * 60 * 60)
_YEAR_TIMEOUT_SECONDS = 365 * 24 * 60 * 60


class TestApplicationWorkflowStack(TstAppABC, TestCase):
    @classmethod
    def get_context(cls):
        with open('cdk.json') as f:
            context = json.load(f)['context']
        context['aws:cdk:bundling-stacks'] = []
        return context

    def test_definition_matches_the_state_table(self):
        stack = self.app.prod_backend_pipeline_stack.prod_stage.application_workflow_stack
        template = Template.from_stack(stack)
        definition = _state_machine_definition(template)
        states = definition['States']

        self.assertEqual('EntryRouter', definition['StartAt'])
        self.assertEqual(_YEAR_TIMEOUT_SECONDS, definition['TimeoutSeconds'])
        self.assertEqual(_table_edges(), _choice_edges(states))
        self._assert_admin_router(states['AdminRouter'])
        self._assert_entry_router(states['EntryRouter'])
        self._assert_every_choice_has_a_default(states)
        self._assert_tasks(states)
        self._assert_terminal_tasks(states)
        self.assertEqual('Succeed', states['Approved']['Next'])
        self.assertEqual('Succeed', states['Rejected']['Next'])
        self.assertEqual('Succeed', states['Deactivated']['Next'])
        self.assertEqual('Succeed', states['DeactivatedOnTimeout']['Next'])
        self.assertEqual('WorkflowFailed', states['InternalError']['Next'])
        self.assertEqual('WorkflowFailed', states['InternalErrorOnInvalidAction']['Next'])
        self.assertEqual('Succeed', states['Succeed']['Type'])
        self.assertEqual('Fail', states['WorkflowFailed']['Type'])
        self.assertNotIn('ApprovedEnsureError', states)
        self.assertNotIn('RejectedEnsureError', states)
        self.assertNotIn('DeactivatedEnsureError', states)

    def test_machine_logging_tracing_and_alarms(self):
        stack = self.app.prod_backend_pipeline_stack.prod_stage.application_workflow_stack
        template = Template.from_stack(stack)
        state_machine = next(iter(template.find_resources('AWS::StepFunctions::StateMachine').values()))
        properties = state_machine['Properties']
        logging_configuration = properties['LoggingConfiguration']

        self.assertEqual('ALL', logging_configuration['Level'])
        self.assertIs(False, logging_configuration['IncludeExecutionData'])
        self.assertIs(True, properties['TracingConfiguration']['Enabled'])

        log_group_ref = logging_configuration['Destinations'][0]['CloudWatchLogsLogGroup']['LogGroupArn']
        logical_id = _logical_id(log_group_ref)
        log_group = template.find_resources(CfnLogGroup.CFN_RESOURCE_TYPE_NAME)[logical_id]
        self.assertIn('KmsKeyId', log_group['Properties'])
        self.assertEqual(30, log_group['Properties']['RetentionInDays'])
        persistent = self.app.prod_backend_pipeline_stack.prod_stage.persistent_stack
        key_id = persistent.get_logical_id(persistent.shared_encryption_key.node.default_child)
        key_policy = json.dumps(Template.from_stack(persistent).find_resources('AWS::KMS::Key')[key_id])
        self.assertIn('logs.', key_policy)
        self.assertIn('.amazonaws.com', key_policy)

        metric_names = {
            alarm['Properties']['MetricName']: alarm['Properties']['AlarmActions']
            for alarm in template.find_resources('AWS::CloudWatch::Alarm').values()
        }
        for metric_name in ('ExecutionsFailed', 'ExecutionsTimedOut', 'ExecutionsAborted'):
            self.assertEqual(1, len(metric_names[metric_name]))

        self._check_no_stack_annotations(stack)

    def test_expiry_schedule_reconciler_and_alarms(self):
        stack = self.app.prod_backend_pipeline_stack.prod_stage.application_workflow_stack
        template = Template.from_stack(stack)

        template.has_resource_properties('AWS::Scheduler::ScheduleGroup', {'Name': 'application-workflow'})
        scheduler_roles = [
            role
            for role in template.find_resources('AWS::IAM::Role').values()
            if _principal_service(role) == 'scheduler.amazonaws.com'
        ]
        self.assertEqual(1, len(scheduler_roles))

        rule = next(iter(template.find_resources('AWS::Events::Rule').values()))
        pattern = rule['Properties']['EventPattern']
        self.assertEqual(['aws.states'], pattern['source'])
        self.assertEqual(['Step Functions Execution Status Change'], pattern['detail-type'])
        self.assertEqual(['FAILED', 'TIMED_OUT', 'ABORTED'], pattern['detail']['status'])
        self.assertEqual(1, len(pattern['detail']['stateMachineArn']))
        self.assertEqual(1, len(rule['Properties']['Targets']))

        actions = _policy_actions(template)
        self.assertIn('states:SendTaskSuccess', actions)
        self.assertIn('states:DescribeExecution', actions)
        self.assertIn('scheduler:DeleteSchedule', actions)
        self.assertIn('lambda:InvokeFunction', actions)

        alarms = list(template.find_resources('AWS::CloudWatch::Alarm').values())
        alarmed_metrics = {alarm['Properties'].get('MetricName') for alarm in alarms}
        for metric_name in (
            'ApplicationExecutionBroken',
            'ApplicationReopenForcedStop',
            'ApplicationExpiryDeactivationFailed',
            'ApplicationCallbackDeliveryExhausted',
            'Errors',
        ):
            self.assertIn(metric_name, alarmed_metrics)
        for alarm in alarms:
            if alarm['Properties'].get('MetricName') in {
                'ApplicationExecutionBroken',
                'ApplicationReopenForcedStop',
                'ApplicationExpiryDeactivationFailed',
                'ApplicationCallbackDeliveryExhausted',
            }:
                self.assertEqual(1, len(alarm['Properties']['AlarmActions']))
        self.assertGreaterEqual(len(template.find_resources('AWS::Logs::MetricFilter')), 4)
        self._check_no_stack_annotations(stack)

    def _assert_admin_router(self, router: dict):
        branches = {(choice['StringEquals'], choice['Next']) for choice in router['Choices']}
        expected = {(state.value, state.value) for state in ADMIN_OVERRIDE_TARGETS}
        self.assertEqual(expected, branches)
        self.assertEqual('InternalErrorOnInvalidAction', router['Default'])
        self.assertTrue(all(choice['Variable'] == '$.transition.targetState' for choice in router['Choices']))

    def _assert_entry_router(self, router: dict):
        self.assertEqual(
            [
                {
                    'Variable': '$.startAt',
                    'StringEquals': StateName.STAFF_REVIEW.value,
                    'Next': StateName.STAFF_REVIEW.value,
                }
            ],
            router['Choices'],
        )
        self.assertEqual(StateName.STARTED.value, router['Default'])

    def _assert_every_choice_has_a_default(self, states: dict):
        for name, state in states.items():
            if state['Type'] == 'Choice':
                self.assertIn('Default', state, msg=name)

    def _assert_tasks(self, states: dict):
        for name, state in states.items():
            if state['Type'] != 'Task':
                continue
            self.assertIn('TimeoutSeconds', state, msg=name)
            self.assertEqual(_LAMBDA_RETRY_ERRORS, state['Retry'][0]['ErrorEquals'])
            self.assertEqual(2, state['Retry'][0]['MaxAttempts'])
            self.assertGreater(state['Retry'][0]['BackoffRate'], 1)
            if state['Resource'].endswith('.waitForTaskToken'):
                self.assertEqual('$.transition', state['ResultPath'])
                self.assertEqual(_WAIT_TIMEOUT_SECONDS, state['TimeoutSeconds'])
                self.assertEqual('States.Timeout', state['Catch'][0]['ErrorEquals'][0])
                self.assertEqual('$.error', state['Catch'][0]['ResultPath'])
                self.assertEqual('DeactivatedOnTimeout', state['Catch'][0]['Next'])
                self.assertEqual('States.ALL', state['Catch'][1]['ErrorEquals'][0])
                self.assertEqual('$.error', state['Catch'][1]['ResultPath'])
                self.assertEqual('InternalError', state['Catch'][1]['Next'])
                payload = state['Parameters']['Payload']
                self.assertEqual(
                    {
                        'compact.$',
                        'applicationId.$',
                        'generation.$',
                        'stateName',
                        'executionArn.$',
                        'enteredTime.$',
                        'taskToken.$',
                    },
                    set(payload),
                )
                self.assertNotIn('mode', payload)
                self.assertEqual(name, payload['stateName'])
                self.assertEqual('$$.Task.Token', payload['taskToken.$'])
            else:
                self.assertNotIn('Catch', state)
                self.assertEqual(30, state['TimeoutSeconds'])
                payload = state['Parameters']['Payload']
                self.assertNotIn('taskToken.$', payload)
                self.assertNotIn('mode', payload)

    def _assert_terminal_tasks(self, states: dict):
        for state_name in (StateName.APPROVED, StateName.REJECTED, StateName.DEACTIVATED):
            payload = states[state_name.value]['Parameters']['Payload']
            self.assertNotIn('error.$', payload)
            self.assertNotIn('error', payload)
            self.assertEqual('$.transition', payload['transition.$'])
            self.assertEqual(state_name.value, payload['stateName'])
        timeout = states['DeactivatedOnTimeout']['Parameters']['Payload']
        self.assertEqual({'reason': 'TIMEOUT'}, timeout['error'])
        self.assertNotIn('error.$', timeout)
        self.assertNotIn('transition.$', timeout)
        self.assertEqual(StateName.DEACTIVATED.value, timeout['stateName'])
        caught = states['InternalError']['Parameters']['Payload']
        self.assertEqual('$.error', caught['error.$'])
        self.assertNotIn('transition.$', caught)
        self.assertEqual(StateName.INTERNAL_ERROR.value, caught['stateName'])
        invalid = states['InternalErrorOnInvalidAction']['Parameters']['Payload']
        self.assertEqual({'reason': 'WORKFLOW_ERROR'}, invalid['error'])
        self.assertNotIn('error.$', invalid)
        self.assertNotIn('transition.$', invalid)
        self.assertEqual(StateName.INTERNAL_ERROR.value, invalid['stateName'])


def _principal_service(role: dict) -> str | None:
    statements = role['Properties'].get('AssumeRolePolicyDocument', {}).get('Statement', [])
    if not statements:
        return None
    service = statements[0].get('Principal', {}).get('Service')
    if isinstance(service, list):
        return service[0]
    return service


def _policy_actions(template: Template) -> set[str]:
    actions = set()
    for policy in template.find_resources('AWS::IAM::Policy').values():
        for statement in policy['Properties']['PolicyDocument']['Statement']:
            action = statement.get('Action', [])
            if isinstance(action, str):
                actions.add(action)
            else:
                actions.update(action)
    return actions


def _table_edges() -> set[tuple[str, str, str]]:
    edges = set()
    for state_name, definition in STATE_DEFINITIONS.items():
        if definition.terminal:
            continue
        for action, target in definition.transitions.items():
            edges.add((state_name.value, action.value, target.value))
        edges.add((state_name.value, WorkflowAction.ADMIN_OVERRIDE.value, 'AdminRouter'))
        edges.add((state_name.value, WorkflowAction.ADMIN_DEACTIVATE.value, StateName.DEACTIVATED.value))
    return edges


def _choice_edges(states: dict) -> set[tuple[str, str, str]]:
    edges = set()
    for name, state in states.items():
        if state['Type'] != 'Task' or not state['Resource'].endswith('.waitForTaskToken'):
            continue
        choice = states[state['Next']]
        for branch in choice['Choices']:
            edges.add((name, branch['StringEquals'], branch['Next']))
    return edges


def _state_machine_definition(template: Template) -> dict:
    resources = template.find_resources('AWS::StepFunctions::StateMachine')
    definition = next(iter(resources.values()))['Properties']['DefinitionString']
    resolved = _resolve(definition)
    if isinstance(resolved, str):
        return json.loads(resolved)
    return resolved


def _resolve(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_resolve(item) for item in value]
    if isinstance(value, dict):
        if 'Fn::Join' in value:
            separator, parts = value['Fn::Join']
            rendered = []
            for part in parts:
                resolved = _resolve(part)
                rendered.append(resolved if isinstance(resolved, str) else json.dumps(resolved))
            return separator.join(rendered)
        if 'Ref' in value:
            return f'${{{value["Ref"]}}}'
        if 'Fn::GetAtt' in value:
            attribute = value['Fn::GetAtt']
            if isinstance(attribute, str):
                return f'${{{attribute}}}'
            return '${' + '.'.join(attribute) + '}'
        return {key: _resolve(item) for key, item in value.items()}
    return value


def _logical_id(value) -> str:
    if isinstance(value, dict) and 'Fn::GetAtt' in value:
        attribute = value['Fn::GetAtt']
        return attribute[0] if isinstance(attribute, list) else attribute.split('.')[0]
    if isinstance(value, dict) and 'Ref' in value:
        return value['Ref']
    raise AssertionError(f'Log group reference was not a template reference: {value}')
