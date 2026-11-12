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
            'dynamodb:TransactGetItems',
            'dynamodb:TransactWriteItems',
        ):
            self.assertIn(action, policies)

        routes = [
            (applications.staff_resource, 'GET', None, None),
            (applications.staff_application_resource, 'GET', None, None),
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

    def test_application_models_follow_the_backend_schemas(self):
        api_stack = self.app.sandbox_backend_stage.api_stack
        template = Template.from_stack(api_stack)
        models = {
            resource['Properties'].get('Description'): resource['Properties']['Schema']
            for resource in template.find_resources(CfnModel.CFN_RESOURCE_TYPE_NAME).values()
        }
        staff = models['Staff view of one application']
        provider = models['Practitioner application']
        education = staff['properties']['education']['properties']
        reviewer = staff['properties']['assignedFirstReviewerMetadata']['properties']

        self.assertEqual('string', education['degreeType']['type'])
        self.assertNotIn('s3Key', json.dumps(staff))
        self.assertNotIn('s3Key', json.dumps(provider))
        self.assertIn('downloadUri', education['transcripts']['items']['properties'])
        self.assertEqual(
            {'cognitoSub', 'firstName', 'lastName', 'assignmentId'},
            set(reviewer),
        )
        for role in (
            'assignedFirstReviewerMetadata',
            'assignedSecondReviewerMetadata',
            'assignedFinalReviewerMetadata',
        ):
            self.assertEqual(reviewer, staff['properties'][role]['properties'])
            self.assertNotIn(role, provider['properties'])
        self.assertIn('Step Functions node', staff['properties']['stateName']['description'])
        self.assertIn('CommitteeFromFirst', staff['properties']['stateName']['enum'])
        list_item = models['Application summaries']['properties']['items']['items']['properties']
        self.assertIn('Step Functions node', list_item['stateName']['description'])
        self.assertEqual(
            ['incomplete', 'complete', 'needs-attention', 'confirm-details'],
            education['calculatedSectionStatusForApplicant']['enum'],
        )
        selected = staff['properties']['reviews']['items']['properties']['reviewerSelectedApplicationStatus']
        self.assertIn('recorded choice', selected['description'])
        self.assertIn('degreeType', models['Provider Education section']['properties'])
        self.assertIn('degreeType', models['Staff Education section']['properties'])
        self.assertNotIn('reviewer', provider['properties']['reviews']['items']['properties'])
        self.assertIn('SUBMIT', models['Transition an application']['properties']['action']['enum'])
        self.assertIn('Started', models['Override an application state']['properties']['targetState']['enum'])
        accepted = models['Accepted application request that has not settled yet']
        self.assertIn('started', accepted['properties']['expectedStatus']['enum'])
        license_status = models['Staff LicenseHistory section']['properties']['licenses']['items']
        self.assertIn('active', license_status['properties']['status']['enum'])
        self.assertIn('Stored section document', models['Stored section document for the path section']['description'])

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
