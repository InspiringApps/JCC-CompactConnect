import json

from aws_cdk.assertions import Match, Template
from aws_cdk.aws_apigateway import CfnMethod, CfnModel, CfnResource
from aws_cdk.aws_lambda import CfnFunction

from tests.app.test_api import TestApi


class TestApplicationsApi(TestApi):
    def test_applicant_routes_use_the_provider_authorizer_and_request_models(self):
        api_stack = self.app.sandbox_backend_stage.api_stack
        api_lambda_stack = self.app.sandbox_backend_stage.api_lambda_stack
        api_template = Template.from_stack(api_stack)
        lambda_template = Template.from_stack(api_lambda_stack)
        applications = api_stack.api.v1_api.applications
        authorizer_id = api_stack.get_logical_id(api_stack.api.provider_users_authorizer.node.default_child)
        integration = TestApi.generate_expected_integration_object_for_imported_lambda(
            api_lambda_stack,
            lambda_template,
            api_lambda_stack.applications_lambdas.applicant_applications_handler,
        )

        lambda_template.has_resource_properties(
            CfnFunction.CFN_RESOURCE_TYPE_NAME,
            {
                'Handler': 'applicant_applications.applicant_applications',
                'Environment': {
                    'Variables': {
                        'APPLICATION_TABLE_NAME': Match.any_value(),
                        'APPLICATION_STATUS_GSI_NAME': Match.any_value(),
                        'APPLICATION_ACTOR_GSI_NAME': Match.any_value(),
                        'APPLICATION_APPLICANT_GSI_NAME': Match.any_value(),
                        'APPLICATION_STATE_MACHINE_ARN': Match.any_value(),
                        'APPLICATION_SCHEDULE_GROUP_NAME': Match.any_value(),
                        'APPLICATION_EXPIRY_FUNCTION_ARN': Match.any_value(),
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
            'scheduler:CreateSchedule',
            'iam:PassRole',
            'dynamodb:TransactGetItems',
            'dynamodb:TransactWriteItems',
        ):
            self.assertIn(action, policies)

        self._assert_route(
            api_template,
            api_stack,
            parent=api_stack.api.v1_api.compact_resource,
            path_part='applications',
        )
        self._assert_method(
            api_template,
            api_stack,
            resource=applications.resource,
            method='POST',
            authorizer_id=authorizer_id,
            integration=integration,
            model_name='V1PostApplicationRequestModel',
            required=['types', 'isRenewal'],
        )
        self._assert_method(
            api_template,
            api_stack,
            resource=applications.resource,
            method='GET',
            authorizer_id=authorizer_id,
            integration=integration,
        )
        self._assert_method(
            api_template,
            api_stack,
            resource=applications.application_resource,
            method='GET',
            authorizer_id=authorizer_id,
            integration=integration,
        )
        self._assert_method(
            api_template,
            api_stack,
            resource=applications.section_resource,
            method='PATCH',
            authorizer_id=authorizer_id,
            integration=integration,
            model_name='V1PatchApplicationSectionRequestModel',
        )
        self._assert_method(
            api_template,
            api_stack,
            resource=applications.submit_resource,
            method='POST',
            authorizer_id=authorizer_id,
            integration=integration,
            model_name='V1PostApplicationSubmissionRequestModel',
        )
        self._assert_method(
            api_template,
            api_stack,
            resource=applications.resubmit_resource,
            method='POST',
            authorizer_id=authorizer_id,
            integration=integration,
            model_name='V1PostApplicationSubmissionRequestModel',
        )

    def _assert_route(self, template: Template, api_stack, parent, path_part: str) -> None:
        template.has_resource_properties(
            CfnResource.CFN_RESOURCE_TYPE_NAME,
            {
                'ParentId': {'Ref': api_stack.get_logical_id(parent.node.default_child)},
                'PathPart': path_part,
            },
        )

    def _assert_method(
        self,
        template: Template,
        api_stack,
        *,
        resource,
        method: str,
        authorizer_id: str,
        integration: dict,
        model_name: str | None = None,
        required: list[str] | None = None,
    ) -> None:
        props = {
            'HttpMethod': method,
            'AuthorizationType': 'COGNITO_USER_POOLS',
            'AuthorizerId': {'Ref': authorizer_id},
            'ResourceId': {'Ref': api_stack.get_logical_id(resource.node.default_child)},
            'Integration': integration,
        }
        if model_name is not None:
            method_properties = self._method_properties(template, resource, method, api_stack)
            model_id = method_properties['RequestModels']['application/json']['Ref']
            schema = template.find_resources(CfnModel.CFN_RESOURCE_TYPE_NAME)[model_id]['Properties']['Schema']
            if required is not None:
                self.assertEqual(required, schema['required'])
            self.assertNotIn('taskToken', json.dumps(schema))
            self.assertNotIn('executionArn', json.dumps(schema))
            props['RequestModels'] = {'application/json': {'Ref': model_id}}
        template.has_resource_properties(CfnMethod.CFN_RESOURCE_TYPE_NAME, props)
        response_id = self._method_properties(template, resource, method, api_stack)['MethodResponses'][0][
            'ResponseModels'
        ]['application/json']['Ref']
        response_schema = template.find_resources(CfnModel.CFN_RESOURCE_TYPE_NAME)[response_id]['Properties']['Schema']
        self.assertNotIn('taskToken', json.dumps(response_schema))
        self.assertNotIn('executionArn', json.dumps(response_schema))
        self.assertIn('RequestValidatorId', self._method_properties(template, resource, method, api_stack))

    def _method_properties(self, template: Template, resource, method: str, api_stack) -> dict:
        resource_id = api_stack.get_logical_id(resource.node.default_child)
        for properties in template.find_resources(CfnMethod.CFN_RESOURCE_TYPE_NAME).values():
            props = properties['Properties']
            if props['HttpMethod'] == method and props['ResourceId'] == {'Ref': resource_id}:
                return props
        self.fail(f'{method} method was not found')
        return {}
