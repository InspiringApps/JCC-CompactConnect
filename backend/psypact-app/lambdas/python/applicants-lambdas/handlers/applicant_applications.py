"""Practitioner application routes."""

import json
from uuid import uuid4

from cc_common.applicants.application_state import Caller, SectionName, WorkflowAction
from cc_common.applicants.schema.api import (
    ApplicantSubmissionRequestSchema,
    CreateApplicationRequestSchema,
    assemble_application_response,
    section_patch_schema,
)
from cc_common.applicants.workflow_lifetime import workflow_lifetime
from cc_common.psypact_api_handler import api_handler_psypact
from cc_common.utils import get_provider_user_attributes_from_authorizer_claims
from common_lambdas import config as config_module
from common_lambdas.exceptions import CCAccessDeniedException, CCInvalidRequestException, CCNotFoundException
from marshmallow import ValidationError

_APPLICATIONS = '/v1/compacts/{compact}/applications'
_APPLICATION = _APPLICATIONS + '/{applicationId}'
_SECTION = _APPLICATION + '/sections/{section}'
_SUBMIT = _APPLICATION + '/submit'
_RESUBMIT = _APPLICATION + '/resubmit'


def _config():
    return config_module.config


def _body(event) -> dict:
    raw = event.get('body')
    if raw is None or raw == '':
        return {}
    if isinstance(raw, dict):
        return raw
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise CCInvalidRequestException('Request body must be an object')
    return loaded


def _load(schema, event) -> dict:
    document = schema() if isinstance(schema, type) else schema
    try:
        return document.load(_body(event))
    except ValidationError as error:
        raise CCInvalidRequestException(json.dumps(error.messages)) from error


def _path(event, name: str) -> str:
    value = (event.get('pathParameters') or {}).get(name)
    if not value:
        raise CCInvalidRequestException(f'Missing {name}')
    return value


def _caller_ids(event) -> tuple[str, str]:
    claim_compact, provider_id = get_provider_user_attributes_from_authorizer_claims(event)
    compact = _path(event, 'compact')
    if claim_compact != compact:
        raise CCAccessDeniedException('Forbidden access attempt!')
    return compact, provider_id


def _caller(event, provider_id: str) -> Caller:
    sub = (event.get('requestContext') or {}).get('authorizer', {}).get('claims', {}).get('sub')
    if not sub:
        raise CCInvalidRequestException('Missing required user profile attribute')
    return Caller(sub=sub, scopes=set(), provider_id=provider_id)


def _require_owner(compact: str, application_id: str, provider_id: str) -> dict:
    application = _config().application_client.get_application(compact, application_id)
    if application is None:
        raise CCNotFoundException('Application not found')
    if application.get('providerId') != provider_id:
        raise CCAccessDeniedException('Forbidden access attempt!')
    return application


def _public(compact: str, application_id: str) -> dict:
    snapshot = _config().application_client.get_snapshot(compact, application_id)
    return _from_snapshot(snapshot)


def _from_snapshot(snapshot) -> dict:
    section_items = [item for item in snapshot.sections.values() if item]
    return assemble_application_response(snapshot.application, section_items)


def _outcome(compact: str, application_id: str, result) -> dict:
    if not result.pending:
        return _public(compact, application_id)
    body = {'id': application_id, 'pending': True}
    if result.expected_status is not None:
        body['expectedStatus'] = result.expected_status
    if result.request_id:
        body['requestId'] = result.request_id
    return body


def _create(event, compact: str, provider_id: str) -> dict:
    loaded = _load(CreateApplicationRequestSchema, event)
    created = _config().current_standard_datetime
    application_id = str(uuid4())
    result = _config().application_transition_service.create_application_and_start(
        compact,
        application_id,
        provider_id=provider_id,
        types=list(loaded['types']),
        is_renewal=bool(loaded['isRenewal']),
        created=created.isoformat(),
        workflow_expires_at=(created + workflow_lifetime()).isoformat(),
    )
    return _outcome(compact, application_id, result)


def _get(compact: str, provider_id: str, event) -> dict:
    application_id = _path(event, 'applicationId')
    _require_owner(compact, application_id, provider_id)
    return _public(compact, application_id)


def _patch(event, compact: str, provider_id: str) -> dict:
    application_id = _path(event, 'applicationId')
    try:
        section = SectionName(_path(event, 'section'))
    except ValueError as error:
        raise CCInvalidRequestException('Unknown section') from error
    _require_owner(compact, application_id, provider_id)
    data = _load(section_patch_schema(section.value), event)
    snapshot = _config().application_client.patch_section(
        compact,
        application_id,
        section,
        data,
        actor_provider_id=provider_id,
    )
    return _from_snapshot(snapshot)[section.value]


def _transition(event, compact: str, provider_id: str, action: WorkflowAction) -> dict:
    application_id = _path(event, 'applicationId')
    loaded = _load(ApplicantSubmissionRequestSchema, event)
    request_id = loaded.get('requestId') or str(uuid4())
    result = _config().application_transition_service.submit_or_transition(
        compact,
        application_id,
        _caller(event, provider_id),
        action,
        request_id,
    )
    return _outcome(compact, application_id, result)


@api_handler_psypact
def applicant_applications(event, context):
    del context
    compact, provider_id = _caller_ids(event)
    method = event['httpMethod']
    resource = event.get('resource') or event['requestContext']['resourcePath']
    if method == 'POST' and resource == _APPLICATIONS:
        return _create(event, compact, provider_id)
    if method == 'GET' and resource == _APPLICATION:
        return _get(compact, provider_id, event)
    if method == 'PATCH' and resource == _SECTION:
        return _patch(event, compact, provider_id)
    if method == 'POST' and resource == _SUBMIT:
        return _transition(event, compact, provider_id, WorkflowAction.SUBMIT)
    if method == 'POST' and resource == _RESUBMIT:
        return _transition(event, compact, provider_id, WorkflowAction.RESUBMIT)
    raise CCInvalidRequestException('Unsupported application route')
