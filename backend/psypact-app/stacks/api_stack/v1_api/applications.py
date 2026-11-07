from __future__ import annotations

from aws_cdk import Duration
from aws_cdk.aws_apigateway import AuthorizationType, LambdaIntegration, MethodResponse, Resource

from common_constructs.cc_api import CCApi
from stacks.api_lambda_stack import ApiLambdaStack

from .api_model import ApiModel


class Applications:
    def __init__(
        self,
        *,
        resource: Resource,
        api_lambda_stack: ApiLambdaStack,
        api_model: ApiModel,
        compact_admin_scopes: list[str],
    ):
        super().__init__()
        self.resource = resource
        self.api: CCApi = resource.api
        self.api_model = api_model
        self.compact_admin_scopes = compact_admin_scopes
        self.handler = api_lambda_stack.applications_lambdas.applicant_applications_handler
        self.staff_handler = api_lambda_stack.applications_lambdas.staff_applications_handler

        # /v1/compacts/{compact}/applications/{applicationId}
        self.application_resource = self.resource.add_resource('{applicationId}')
        # /v1/compacts/{compact}/applications/{applicationId}/sections/{section}
        self.sections_resource = self.application_resource.add_resource('sections')
        self.section_resource = self.sections_resource.add_resource('{section}')
        # /v1/compacts/{compact}/applications/{applicationId}/submit
        self.submit_resource = self.application_resource.add_resource('submit')
        # /v1/compacts/{compact}/applications/{applicationId}/resubmit
        self.resubmit_resource = self.application_resource.add_resource('resubmit')

        self._add_create()
        self._add_get()
        self._add_patch_section()
        self._add_submit()
        self._add_resubmit()
        self._add_staff_routes()

    def _integration(self) -> LambdaIntegration:
        return LambdaIntegration(self.handler, timeout=Duration.seconds(29))

    def _method_options(self) -> dict:
        return {
            'request_validator': self.api.parameter_body_validator,
            'request_parameters': {'method.request.header.Authorization': True},
            'authorizer': self.api.provider_users_authorizer,
            'integration': self._integration(),
        }

    def _add_create(self) -> None:
        self.resource.add_method(
            'POST',
            request_models={'application/json': self.api_model.post_application_request_model},
            method_responses=[
                MethodResponse(
                    status_code='200',
                    response_models={'application/json': self.api_model.application_response_model},
                ),
                MethodResponse(
                    status_code='202',
                    response_models={'application/json': self.api_model.application_accepted_response_model},
                ),
            ],
            **self._method_options(),
        )

    def _add_get(self) -> None:
        self.application_resource.add_method(
            'GET',
            method_responses=[
                MethodResponse(
                    status_code='200',
                    response_models={'application/json': self.api_model.application_response_model},
                ),
            ],
            **self._method_options(),
        )

    def _add_patch_section(self) -> None:
        self.section_resource.add_method(
            'PATCH',
            request_models={'application/json': self.api_model.patch_application_section_request_model},
            method_responses=[
                MethodResponse(
                    status_code='200',
                    response_models={'application/json': self.api_model.application_section_response_model},
                ),
                MethodResponse(
                    status_code='409',
                    response_models={'application/json': self.api_model.message_response_model},
                ),
            ],
            **self._method_options(),
        )

    def _add_submit(self) -> None:
        self._add_submission(self.submit_resource)

    def _add_resubmit(self) -> None:
        self._add_submission(self.resubmit_resource)

    def _add_staff_routes(self) -> None:
        # Practitioner GET stays on {applicationId}. A method can have one authorizer,
        # so staff detail is a separate route on the compact-admin authorizer.
        self.detail_resource = self.application_resource.add_resource('detail')
        self.reviewers_resource = self.application_resource.add_resource('reviewers')
        self.section_review_resource = self.section_resource.add_resource('review')
        self.transition_resource = self.application_resource.add_resource('transition')
        self.admin_resource = self.application_resource.add_resource('admin')
        self.admin_status_resource = self.admin_resource.add_resource('status')
        self.reopen_resource = self.application_resource.add_resource('reopen')

        self.detail_resource.add_method(
            'GET',
            method_responses=[
                MethodResponse(
                    status_code='200',
                    response_models={'application/json': self.api_model.staff_application_response_model},
                ),
            ],
            **self._staff_options(),
        )
        self.resource.add_method(
            'GET',
            method_responses=[
                MethodResponse(
                    status_code='200',
                    response_models={'application/json': self.api_model.staff_application_list_response_model},
                ),
            ],
            **self._staff_options(query=True),
        )
        self._add_staff_mutation(
            self.reviewers_resource,
            'PUT',
            self.api_model.put_application_reviewers_request_model,
        )
        self.section_review_resource.add_method(
            'PUT',
            request_models={'application/json': self.api_model.put_application_section_review_request_model},
            method_responses=[
                MethodResponse(
                    status_code='200',
                    response_models={'application/json': self.api_model.application_section_response_model},
                ),
                MethodResponse(
                    status_code='409',
                    response_models={'application/json': self.api_model.message_response_model},
                ),
            ],
            **self._staff_options(),
        )
        self._add_staff_mutation(
            self.transition_resource,
            'POST',
            self.api_model.post_application_transition_request_model,
        )
        self._add_staff_mutation(
            self.admin_status_resource,
            'POST',
            self.api_model.post_application_status_request_model,
        )
        self._add_staff_mutation(
            self.reopen_resource,
            'POST',
            self.api_model.post_application_reopen_request_model,
        )

    def _add_staff_mutation(self, resource: Resource, method: str, request_model) -> None:
        resource.add_method(
            method,
            request_models={'application/json': request_model},
            method_responses=[
                MethodResponse(
                    status_code='200',
                    response_models={'application/json': self.api_model.staff_application_response_model},
                ),
                MethodResponse(
                    status_code='202',
                    response_models={'application/json': self.api_model.application_accepted_response_model},
                ),
                MethodResponse(
                    status_code='409',
                    response_models={'application/json': self.api_model.message_response_model},
                ),
            ],
            **self._staff_options(),
        )

    def _staff_options(self, *, query: bool = False) -> dict:
        parameters = {'method.request.header.Authorization': True}
        if query:
            parameters.update(
                {
                    'method.request.querystring.status': False,
                    'method.request.querystring.mine': False,
                    'method.request.querystring.pageSize': False,
                    'method.request.querystring.lastKey': False,
                }
            )
        return {
            'request_validator': self.api.parameter_body_validator,
            'request_parameters': parameters,
            'authorization_type': AuthorizationType.COGNITO,
            'authorizer': self.api.staff_users_authorizer,
            'authorization_scopes': self.compact_admin_scopes,
            'integration': LambdaIntegration(self.staff_handler, timeout=Duration.seconds(29)),
        }

    def _add_submission(self, resource: Resource) -> None:
        resource.add_method(
            'POST',
            request_models={'application/json': self.api_model.post_application_submission_request_model},
            method_responses=[
                MethodResponse(
                    status_code='200',
                    response_models={'application/json': self.api_model.application_response_model},
                ),
                MethodResponse(
                    status_code='202',
                    response_models={'application/json': self.api_model.application_accepted_response_model},
                ),
            ],
            **self._method_options(),
        )
