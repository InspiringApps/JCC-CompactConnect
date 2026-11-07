import json

from aws_cdk.assertions import Match, Template
from aws_cdk.aws_apigateway import CfnMethod, CfnModel
from aws_cdk.aws_lambda import CfnFunction

from tests.app.test_api import TestApi


class TestApplicationsStaffApi(TestApi):
    def test_staff_routes_are_compact_admin_only(self):
        api_stack = self.app.sandbox_backend_stage.api_stack
        api_lambda_stack = self.app.sandbox_backend_stage.api_lambda_stack
        api_template = Template.from_stack(api_stack)
        lambda_template = Template.from_stack(api_lambda_stack)
        applications = api_stack.api.v1_api.applications
        authorizer_id = api_stack.get_logical_id(api_stack.api.staff_users_authorizer.node.default_child)
        integration = TestApi.generate_expected_integration_object_for_imported_lambda(
            api_lambda_stack,
            lambda_template,
            api_lambda_stack.applications_lambdas.staff_applications_handler,
        )

        lambda_template.has_resource_properties(
            CfnFunction.CFN_RESOURCE_TYPE_NAME,
            {
                'Handler': 'staff_applications.staff_applications',
                'Environment': {
                    'Variables': {
                        'APPLICATION_TABLE_NAME': Match.any_value(),
                        'APPLICATION_STATUS_GSI_NAME': Match.any_value(),
                        'APPLICATION_ACTOR_GSI_NAME': Match.any_value(),
                        'USERS_TABLE_NAME': Match.any_value(),
                        'APPLICATION_STATE_MACHINE_ARN': Match.any_value(),
                        'APPLICATION_SCHEDULE_GROUP_NAME': Match.any_value(),
                        'APPLICATION_SCHEDULER_ROLE_ARN': Match.any_value(),
                    }
                },
            },
        )
        policies = json.dumps(lambda_template.find_resources('AWS::IAM::Policy'))
        for action in (
            'states:StartExecution',
            'states:SendTaskSuccess',
            'states:DescribeExecution',
            'states:StopExecution',
            'scheduler:CreateSchedule',
            'scheduler:DeleteSchedule',
            'iam:PassRole',
        ):
            self.assertIn(action, policies)

        routes = [
            (applications.resource, 'GET', None, None),
            (applications.detail_resource, 'GET', None, None),
            (applications.reviewers_resource, 'PUT', 'V1PutApplicationReviewersRequestModel', None),
            (
                applications.section_review_resource,
                'PUT',
                'V1PutApplicationSectionReviewRequestModel',
                ['sectionStatus'],
            ),
            (
                applications.transition_resource,
                'POST',
                'V1PostApplicationTransitionRequestModel',
                ['action', 'requestId'],
            ),
            (
                applications.admin_status_resource,
                'POST',
                'V1PostApplicationStatusRequestModel',
                ['targetState', 'requestId'],
            ),
            (applications.reopen_resource, 'POST', 'V1PostApplicationReopenRequestModel', None),
        ]
        for resource, method, model_name, required in routes:
            self._assert_compact_admin_method(
                api_template,
                api_stack,
                resource=resource,
                method=method,
                authorizer_id=authorizer_id,
                integration=integration,
                model_name=model_name,
                required=required,
            )

    def _assert_compact_admin_method(
        self,
        template: Template,
        api_stack,
        *,
        resource,
        method: str,
        authorizer_id: str,
        integration: dict,
        model_name: str | None,
        required: list[str] | None,
    ) -> None:
        properties = self._method_properties(template, resource, method, api_stack)
        scopes = properties['AuthorizationScopes']
        self.assertTrue(scopes)
        for scope in scopes:
            self.assertTrue(str(scope).endswith('/admin'))
            self.assertNotIn('.admin', str(scope))
        props = {
            'HttpMethod': method,
            'AuthorizationType': 'COGNITO_USER_POOLS',
            'AuthorizerId': {'Ref': authorizer_id},
            'AuthorizationScopes': scopes,
            'ResourceId': {'Ref': api_stack.get_logical_id(resource.node.default_child)},
            'Integration': integration,
        }
        if model_name is not None:
            model_id = properties['RequestModels']['application/json']['Ref']
            schema = template.find_resources(CfnModel.CFN_RESOURCE_TYPE_NAME)[model_id]['Properties']['Schema']
            if required is not None:
                self.assertEqual(required, schema['required'])
            self.assertNotIn('taskToken', json.dumps(schema))
            self.assertNotIn('executionArn', json.dumps(schema))
            props['RequestModels'] = {'application/json': {'Ref': model_id}}
        template.has_resource_properties(CfnMethod.CFN_RESOURCE_TYPE_NAME, props)
        response_id = properties['MethodResponses'][0]['ResponseModels']['application/json']['Ref']
        response_schema = template.find_resources(CfnModel.CFN_RESOURCE_TYPE_NAME)[response_id]['Properties']['Schema']
        self.assertNotIn('taskToken', json.dumps(response_schema))
        self.assertNotIn('executionArn', json.dumps(response_schema))

    def _method_properties(self, template: Template, resource, method: str, api_stack) -> dict:
        resource_id = api_stack.get_logical_id(resource.node.default_child)
        for properties in template.find_resources(CfnMethod.CFN_RESOURCE_TYPE_NAME).values():
            candidate = properties['Properties']
            if candidate['HttpMethod'] == method and candidate['ResourceId'] == {'Ref': resource_id}:
                return candidate
        raise AssertionError(f'{method} was not found')
