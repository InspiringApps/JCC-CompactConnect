"""Compact-admin application routes.

List reads use ``statusGSI`` and ``actorGSI``. Both indexes are eventually consistent,
so a list result must not be used to authorize an action.
"""

import json
from uuid import uuid4

from cc_common.applicants.application_client import actor_sub_for_state
from cc_common.applicants.application_state import (
    REVIEWER_ROLES,
    STATE_DEFINITIONS,
    ApplicationStatus,
    Caller,
    SectionName,
    StateName,
    WorkflowAction,
)
from cc_common.applicants.schema.api import (
    AssignReviewersRequestSchema,
    ReopenApplicationRequestSchema,
    SectionReviewRequestSchema,
    SetApplicationStatusRequestSchema,
    StaffApplicationResponseSchema,
    TransitionRequestSchema,
    assemble_application_response,
)
from cc_common.psypact_api_handler import api_handler_psypact
from common_lambdas import config as config_module
from common_lambdas.exceptions import (
    CCAccessDeniedException,
    CCInvalidRequestException,
    CCNotFoundException,
)
from common_lambdas.utils import authorize_compact_level_only_action
from marshmallow import ValidationError

_APPLICATIONS = '/v1/compacts/{compact}/staff-users/applications'
_APPLICATION = _APPLICATIONS + '/{applicationId}'
_REVIEWERS = _APPLICATION + '/reviewers'
_SECTION_REVIEW = _APPLICATION + '/sections/{section}/review'
_TRANSITION = _APPLICATION + '/transition'
_ADMIN_STATUS = _APPLICATION + '/admin/status'
_REOPEN = _APPLICATION + '/reopen'
_REVIEWER_NAMES = (
    ('firstReviewerSub', 'firstReviewerFirstName', 'firstReviewerLastName'),
    ('secondReviewerSub', 'secondReviewerFirstName', 'secondReviewerLastName'),
    ('finalReviewerSub', 'finalReviewerFirstName', 'finalReviewerLastName'),
)
_ACTOR_PREFIX = '#ACTOR#'


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


def _caller(event) -> Caller:
    claims = (event.get('requestContext') or {}).get('authorizer', {}).get('claims', {})
    sub = claims.get('sub')
    if not sub:
        raise CCInvalidRequestException('Missing required user profile attribute')
    return Caller(sub=sub, scopes=set(str(claims.get('scope') or '').split()))


def _require_application(compact: str, application_id: str) -> dict:
    application = _config().application_client.get_application(compact, application_id)
    if application is None:
        raise CCNotFoundException('Application not found')
    return application


def _from_snapshot(snapshot) -> dict:
    section_items = [item for item in snapshot.sections.values() if item]
    return assemble_application_response(
        snapshot.application,
        section_items,
        response_schema=StaffApplicationResponseSchema,
    )


def _read(compact: str, application_id: str) -> dict:
    return _from_snapshot(_config().application_client.get_snapshot(compact, application_id))


def _outcome(compact: str, application_id: str, result) -> dict:
    if not result.pending:
        return _read(compact, application_id)
    body = {'id': application_id, 'pending': True}
    if result.expected_status is not None:
        body['expectedStatus'] = result.expected_status
    if result.request_id:
        body['requestId'] = result.request_id
    return body


def _pagination(event) -> dict:
    params = event.get('queryStringParameters') or {}
    pagination = {}
    if params.get('pageSize') is not None:
        try:
            pagination['pageSize'] = int(params['pageSize'])
        except ValueError as error:
            raise CCInvalidRequestException('pageSize must be an integer') from error
    if params.get('lastKey'):
        pagination['lastKey'] = params['lastKey']
    return pagination


def _summary(compact: str, item: dict) -> dict:
    application_id = item.get('applicationId') or item.get('id')
    actor_key = item.get('actorGSIPK')
    marker = f'{compact}{_ACTOR_PREFIX}'
    if isinstance(actor_key, str) and actor_key.startswith(marker):
        actor_sub = actor_key[len(marker) :]
    elif item.get('stateName'):
        actor_sub = actor_sub_for_state(item, item['stateName'])
    else:
        actor_sub = None
    return {
        'id': application_id,
        'status': item.get('status'),
        'stateName': item.get('stateName'),
        'providerId': item.get('providerId'),
        'types': item.get('types'),
        'submitted': item.get('submitted'),
        'actorSub': actor_sub,
    }


def _list(event, compact: str, caller: Caller) -> dict:
    """Return application summaries from an eventually consistent index."""
    params = event.get('queryStringParameters') or {}
    client = _config().application_client
    pagination = _pagination(event)
    if str(params.get('mine', '')).lower() == 'true':
        page = client.query_by_actor(compact, caller.sub, pagination)
    else:
        try:
            status = ApplicationStatus(params.get('status')).value
        except ValueError as error:
            raise CCInvalidRequestException('status is not a valid application status') from error
        page = client.query_by_status(compact, status, pagination)
    return {
        'items': [_summary(compact, item) for item in page['items']],
        'pagination': page['pagination'],
    }


def _compact_admin(compact: str, user_id: str) -> tuple[str | None, str | None]:
    try:
        user = _config().user_client.get_user_in_compact(compact=compact, user_id=user_id, consistent_read=True)
    except (CCNotFoundException, ValidationError) as error:
        raise CCInvalidRequestException('Reviewer is not a compact admin') from error
    actions = set((user.get('permissions') or {}).get('actions') or [])
    if 'admin' not in actions:
        raise CCInvalidRequestException('Reviewer is not a compact admin')
    attributes = user.get('attributes') or {}
    return attributes.get('givenName'), attributes.get('familyName')


def _assign_reviewers(event, compact: str, caller: Caller) -> dict:
    application_id = _path(event, 'applicationId')
    loaded = _load(AssignReviewersRequestSchema, event)
    for sub_field, first_field, last_field in _REVIEWER_NAMES:
        sub = loaded.get(sub_field)
        if not sub:
            continue
        given_name, family_name = _compact_admin(compact, sub)
        if given_name:
            loaded[first_field] = given_name
        if family_name:
            loaded[last_field] = family_name
    application = _require_application(compact, application_id)
    result = _config().application_client.assign_reviewers(
        compact,
        application_id,
        loaded,
        expected_version=int(application['version']),
    )
    in_staff_review = application.get('stateName') == StateName.STAFF_REVIEW.value
    if in_staff_review and result.all_reviewers_set:
        transition = _config().application_transition_service.submit_or_transition(
            compact,
            application_id,
            caller,
            WorkflowAction.REVIEWERS_ASSIGNED,
            str(uuid4()),
        )
        return _outcome(compact, application_id, transition)
    return _from_snapshot(result.snapshot)


def _section_review(event, compact: str, caller: Caller) -> dict:
    application_id = _path(event, 'applicationId')
    try:
        section = SectionName(_path(event, 'section'))
    except ValueError as error:
        raise CCInvalidRequestException('Unknown section') from error
    loaded = _load(SectionReviewRequestSchema, event)
    if not loaded.get('sectionStatus'):
        raise CCInvalidRequestException('sectionStatus is required')
    application = _require_application(compact, application_id)
    try:
        state_name = StateName(application.get('stateName'))
    except ValueError as error:
        raise CCInvalidRequestException('Section review is not allowed from this state') from error
    role = STATE_DEFINITIONS[state_name].actor_role
    if role not in REVIEWER_ROLES:
        raise CCInvalidRequestException('Section review is not allowed from this state')
    if actor_sub_for_state(application, state_name) != caller.sub:
        raise CCAccessDeniedException('Forbidden access attempt!')
    notes = {
        field_name: loaded[field_name]
        for field_name in ('notesForApplicant', 'notesForReviewers')
        if loaded.get(field_name) is not None
    }
    snapshot = _config().application_client.save_section_review(
        compact,
        application_id,
        section,
        role,
        caller.sub,
        loaded['sectionStatus'],
        notes or None,
    )
    return _from_snapshot(snapshot)[section.value]


def _transition(event, compact: str, caller: Caller) -> dict:
    application_id = _path(event, 'applicationId')
    loaded = _load(TransitionRequestSchema, event)
    result = _config().application_transition_service.submit_or_transition(
        compact,
        application_id,
        caller,
        loaded['action'],
        loaded['requestId'],
        notes_for_applicant=loaded.get('notesForApplicant'),
        notes_for_reviewers=loaded.get('notesForReviewers'),
    )
    return _outcome(compact, application_id, result)


def _admin_status(event, compact: str, caller: Caller) -> dict:
    application_id = _path(event, 'applicationId')
    loaded = _load(SetApplicationStatusRequestSchema, event)
    result = _config().application_transition_service.admin_override(
        compact,
        application_id,
        caller,
        loaded['requestId'],
        loaded['targetState'],
        notes_for_reviewers=loaded.get('reason'),
    )
    return _outcome(compact, application_id, result)


def _reopen(event, compact: str, caller: Caller) -> dict:
    application_id = _path(event, 'applicationId')
    loaded = _load(ReopenApplicationRequestSchema, event)
    result = _config().application_reopen_service.reopen(
        compact,
        application_id,
        caller,
        loaded.get('requestId') or str(uuid4()),
        loaded.get('reason') or '',
    )
    return _outcome(compact, application_id, result)


@api_handler_psypact
@authorize_compact_level_only_action('admin')
def staff_applications(event, context):
    del context
    compact = _path(event, 'compact')
    caller = _caller(event)
    method = event['httpMethod']
    resource = event.get('resource') or event['requestContext']['resourcePath']
    if method == 'GET' and resource == _APPLICATIONS:
        return _list(event, compact, caller)
    if method == 'GET' and resource == _APPLICATION:
        return _read(compact, _path(event, 'applicationId'))
    if method == 'PUT' and resource == _REVIEWERS:
        return _assign_reviewers(event, compact, caller)
    if method == 'PUT' and resource == _SECTION_REVIEW:
        return _section_review(event, compact, caller)
    if method == 'POST' and resource == _TRANSITION:
        return _transition(event, compact, caller)
    if method == 'POST' and resource == _ADMIN_STATUS:
        return _admin_status(event, compact, caller)
    if method == 'POST' and resource == _REOPEN:
        return _reopen(event, compact, caller)
    raise CCInvalidRequestException('Unsupported application route')
