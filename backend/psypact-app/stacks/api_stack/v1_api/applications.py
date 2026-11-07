from __future__ import annotations

from aws_cdk import Duration
from aws_cdk.aws_apigateway import LambdaIntegration, MethodResponse, Resource

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
    ):
        super().__init__()
        self.resource = resource
        self.api: CCApi = resource.api
        self.api_model = api_model
        self.handler = api_lambda_stack.applications_lambdas.applicant_applications_handler

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
