"""DynamoDB access for practitioner applications.

Transactions use the low-level DynamoDB client and ``TypeSerializer`` / ``TypeDeserializer``.
The resource ``Table`` API cannot express ``TransactGetItems`` or ``TransactWriteItems``.
"""

import json
from base64 import b64decode, b64encode
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
from common_lambdas.exceptions import CCConflictException, CCInvalidRequestException, CCNotFoundException

from cc_common.applicants.application_state import (
    APPLICANT_EDITABLE_STATES,
    STATE_DEFINITIONS,
    ActorRole,
    ApplicationStatus,
    ReviewerType,
    ReviewSectionStatus,
    SectionName,
    StateName,
    WorkflowAction,
    reviewer_edit_states,
    validate_reviewer_assignment,
)
from cc_common.applicants.workflow_lifetime import workflow_lifetime

APPLICATION_SK = 'APPLICATION'
APPLICATION_RECORD_TYPE = 'application'
APPLICATION_SECTION_RECORD_TYPE = 'applicationSection'
APPLICATION_TRANSITION_RECORD_TYPE = 'applicationTransition'
APPLICATION_REQUEST_RECORD_TYPE = 'applicationRequest'

_REVIEWER_SUB_FIELDS = {
    ActorRole.FIRST_REVIEWER: 'firstReviewerSub',
    ActorRole.SECOND_REVIEWER: 'secondReviewerSub',
    ActorRole.FINAL_REVIEWER: 'finalReviewerSub',
}

_ROLE_FIELDS = {
    ActorRole.FIRST_REVIEWER: (
        'firstReviewerSub',
        'firstReviewerAssignmentId',
        'firstReviewerFirstName',
        'firstReviewerLastName',
        ReviewerType.FIRST_REVIEWER,
    ),
    ActorRole.SECOND_REVIEWER: (
        'secondReviewerSub',
        'secondReviewerAssignmentId',
        'secondReviewerFirstName',
        'secondReviewerLastName',
        ReviewerType.SECOND_REVIEWER,
    ),
    ActorRole.FINAL_REVIEWER: (
        'finalReviewerSub',
        'finalReviewerAssignmentId',
        'finalReviewerFirstName',
        'finalReviewerLastName',
        ReviewerType.FINAL_REVIEWER,
    ),
}

_ASSIGNABLE_STATUSES = (
    ApplicationStatus.STAFF_REVIEW,
    ApplicationStatus.FIRST_REVIEW,
    ApplicationStatus.SECOND_REVIEW,
    ApplicationStatus.FINAL_REVIEW,
    ApplicationStatus.COMMITTEE_REVIEW,
)

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()
_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 100


def task_token_hash(task_token: str) -> str:
    """Return the stored hash of a Step Functions task token."""
    return sha256(task_token.encode('utf-8')).hexdigest()


def _serialize_item(item: Mapping) -> dict:
    return {key: _serializer.serialize(value) for key, value in item.items()}


def _deserialize_item(item: Mapping) -> dict:
    return {key: _deserializer.deserialize(value) for key, value in item.items()}


def _attribute_values(values: Mapping) -> dict:
    return {key: _serializer.serialize(value) for key, value in values.items()}


def _state(state_name: StateName | str) -> StateName:
    return state_name if isinstance(state_name, StateName) else StateName(state_name)


def _string_value(value) -> str:
    return value.value if hasattr(value, 'value') else str(value)


def _query_page_size(raw_page_size) -> int:
    """Return a DynamoDB Limit. Absent or empty input keeps the default of 100."""
    if raw_page_size is None or raw_page_size == '':
        return _DEFAULT_PAGE_SIZE
    # bool is an int subclass, and a float would be truncated by int().
    if isinstance(raw_page_size, bool) or not isinstance(raw_page_size, (int, str)):
        raise CCInvalidRequestException('pageSize must be an integer')
    try:
        page_size = int(raw_page_size)
    except ValueError as error:
        raise CCInvalidRequestException('pageSize must be an integer') from error
    if page_size < 1 or page_size > _MAX_PAGE_SIZE:
        raise CCInvalidRequestException(f'pageSize must be between 1 and {_MAX_PAGE_SIZE}')
    return page_size


def actor_sub_for_state(application_item: Mapping, state_name: StateName | str) -> str | None:
    """Return the sub ``EnterState`` should place on ``actorGSI`` for this state.

    The applicant actor is the application's ``providerId``. Reviewer roles use that
    role's assigned sub. Staff review and terminal states have no actor sub.
    """
    definition = STATE_DEFINITIONS[_state(state_name)]
    if definition.terminal or definition.actor_role is None:
        return None
    if definition.actor_role is ActorRole.APPLICANT:
        provider_id = application_item.get('providerId')
        return None if provider_id is None else str(provider_id)
    if definition.actor_role is ActorRole.COMPACT_ADMIN:
        return None
    field_name = _REVIEWER_SUB_FIELDS.get(definition.actor_role)
    if field_name is None:
        return None
    reviewer_sub = application_item.get(field_name)
    return None if reviewer_sub is None else str(reviewer_sub)


def _condition_failed(error: ClientError) -> bool:
    if error.response['Error']['Code'] != 'TransactionCanceledException':
        return False
    reasons = error.response.get('CancellationReasons') or []
    codes = [reason.get('Code') for reason in reasons if reason]
    return not codes or 'ConditionalCheckFailed' in codes


def _reconciler_targets(application: Mapping | None, execution_arn: str, generation: int) -> bool:
    if not application:
        return False
    return int(application.get('generation') or 0) == generation and application.get('executionArn') == execution_arn


def _already_reconciled(application: Mapping | None, reason: str) -> bool:
    if not application:
        return False
    return (
        application.get('status') == ApplicationStatus.DEACTIVATED.value
        and application.get('deactivationReason') == reason
    )


def _is_conflict(error: ClientError) -> bool:
    if error.response['Error']['Code'] == 'ConditionalCheckFailedException':
        return True
    return _condition_failed(error)


def _actor_role(role: ActorRole | str) -> ActorRole:
    return role if isinstance(role, ActorRole) else ActorRole(role)


def _merge_section_data(existing: Mapping | None, patch: Mapping | None) -> dict:
    merged = dict(existing or {})
    merged.update(dict(patch or {}))
    return merged


def _reviewer_identity(sub: str, first_name: str | None, last_name: str | None) -> dict:
    reviewer = {'id': sub}
    if first_name:
        reviewer['firstName'] = first_name
    if last_name:
        reviewer['lastName'] = last_name
    return reviewer


def _review_shell(
    *,
    assignment_id: str,
    reviewer_type: ReviewerType,
    sub: str,
    first_name: str | None,
    last_name: str | None,
    assigned_date: str,
    section: bool,
) -> dict:
    shell = {
        'assignmentId': assignment_id,
        'reviewerType': reviewer_type.value,
        'reviewer': _reviewer_identity(sub, first_name, last_name),
        'assignedDate': assigned_date,
    }
    if section:
        shell['reviewerSelectedApplicationSectionStatus'] = ReviewSectionStatus.PENDING.value
    return shell


def _matching_review(reviews: list | None, *, reviewer_type: str, sub: str | None, assignment_id: str | None):
    """Return the review whose type, reviewer sub, and assignment id all match."""
    if not reviews or not sub or not assignment_id:
        return None
    for index, review in enumerate(reviews):
        reviewer = review.get('reviewer') or {}
        if (
            review.get('reviewerType') == reviewer_type
            and review.get('assignmentId') == assignment_id
            and reviewer.get('id') == sub
        ):
            return index, review
    return None


def _locate_active_review(application_item: Mapping, role: ActorRole | str) -> dict | None:
    """Return the current assignment's application review, or None when it is absent.

    The match is reviewer type, the role's current sub, and that role's current assignment id.
    A sub alone is not enough, because one person may hold more than one role.
    """
    actor_role = _actor_role(role)
    sub_field, assignment_field, _first_name, _last_name, reviewer_type = _ROLE_FIELDS[actor_role]
    located = _matching_review(
        application_item.get('reviews'),
        reviewer_type=reviewer_type.value,
        sub=application_item.get(sub_field),
        assignment_id=application_item.get(assignment_field),
    )
    if located is None:
        return None
    return located[1]


def _locate_active_section_review(
    section_item: Mapping, application_item: Mapping, role: ActorRole | str
) -> dict | None:
    """Return the current assignment's section review, or None when it is absent."""
    actor_role = _actor_role(role)
    sub_field, assignment_field, _first_name, _last_name, reviewer_type = _ROLE_FIELDS[actor_role]
    located = _matching_review(
        section_item.get('reviews'),
        reviewer_type=reviewer_type.value,
        sub=application_item.get(sub_field),
        assignment_id=application_item.get(assignment_field),
    )
    if located is None:
        return None
    return located[1]


def _recorded_token_matches(item: Mapping, task_token: str | None, *, terminal: bool) -> bool:
    stored = item.get('taskTokenHash')
    if terminal:
        return stored is None and not task_token
    if not task_token or stored is None:
        return False
    return stored == task_token_hash(task_token)


@dataclass(frozen=True, slots=True)
class ApplicationSnapshot:
    """Serializable read of the application item and its six section items."""

    application: dict
    sections: dict[SectionName, dict]


@dataclass(frozen=True, slots=True)
class ReviewerAssignmentResult:
    """Result of assigning one or more reviewers."""

    snapshot: ApplicationSnapshot
    all_reviewers_set: bool


class ApplicationClient:
    """Read and write application-table items."""

    def __init__(self, config):
        self.config = config

    @staticmethod
    def pk(compact: str, application_id: str) -> str:
        return f'{compact}#APPLICATION#{application_id}'

    @staticmethod
    def section_sk(name: SectionName | str) -> str:
        return f'SECTION#{_string_value(name)}'

    @staticmethod
    def transition_sk(entered_time: str, state_name: StateName | str) -> str:
        return f'TRANSITION#{entered_time}#{_string_value(state_name)}'

    @staticmethod
    def request_sk(request_id: str) -> str:
        return f'REQUEST#{request_id}'

    def get_application(self, compact: str, application_id: str) -> dict | None:
        """Return the APPLICATION item, or None when it does not exist."""
        response = self.config.dynamodb_client.get_item(
            TableName=self.config.application_table_name,
            Key=_serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
            ConsistentRead=True,
        )
        item = response.get('Item')
        if not item:
            return None
        return _deserialize_item(item)

    def get_snapshot(self, compact: str, application_id: str) -> ApplicationSnapshot:
        """Read the APPLICATION item and all six SECTION items in one transaction."""
        partition_key = self.pk(compact, application_id)
        keys = [{'pk': partition_key, 'sk': APPLICATION_SK}]
        keys.extend({'pk': partition_key, 'sk': self.section_sk(section)} for section in SectionName)
        response = self.config.dynamodb_client.transact_get_items(
            TransactItems=[
                {
                    'Get': {
                        'TableName': self.config.application_table_name,
                        'Key': _serialize_item(key),
                    }
                }
                for key in keys
            ]
        )
        items = []
        for entry in response.get('Responses', []):
            raw_item = entry.get('Item')
            items.append(_deserialize_item(raw_item) if raw_item else None)

        application = items[0] if items else None
        if not application:
            raise CCNotFoundException('Application not found')

        sections = {}
        for section, item in zip(SectionName, items[1:], strict=True):
            sections[section] = item or {}
        return ApplicationSnapshot(application=application, sections=sections)

    def query_all_items(self, compact: str, application_id: str) -> list[dict]:
        """Return every item in the application partition.

        The query uses a consistent read so a caller assembling a read-only response
        sees committed writes. It is not a transactional snapshot: items are not read
        at one serializable point in time.
        """
        items = []
        query = {
            'TableName': self.config.application_table_name,
            'KeyConditionExpression': 'pk = :pk',
            'ExpressionAttributeValues': _attribute_values({':pk': self.pk(compact, application_id)}),
            'ConsistentRead': True,
        }
        while True:
            response = self.config.dynamodb_client.query(**query)
            items.extend(_deserialize_item(item) for item in response.get('Items', []))
            last_key = response.get('LastEvaluatedKey')
            if not last_key:
                return items
            query['ExclusiveStartKey'] = last_key

    def query_by_status(self, compact: str, status: str, pagination: dict | None = None) -> dict:
        """Query statusGSI.

        The index is eventually consistent. Do not use its result to authorize an action.
        """
        return self._query_index(
            self.config.application_status_gsi_name,
            'statusGSIPK',
            f'{compact}#STATUS#{status}',
            pagination,
        )

    def query_by_actor(self, compact: str, actor_sub: str, pagination: dict | None = None) -> dict:
        """Query actorGSI.

        The index is eventually consistent. Do not use its result to authorize an action.
        """
        return self._query_index(
            self.config.application_actor_gsi_name,
            'actorGSIPK',
            f'{compact}#ACTOR#{actor_sub}',
            pagination,
        )

    def _query_index(self, index_name: str, key_name: str, key_value: str, pagination: dict | None) -> dict:
        pagination = pagination or {}
        page_size = _query_page_size(pagination.get('pageSize'))
        query = {
            'IndexName': index_name,
            'KeyConditionExpression': Key(key_name).eq(key_value),
            'Limit': page_size,
        }
        last_key = pagination.get('lastKey')
        if last_key:
            try:
                decoded = json.loads(b64decode(last_key).decode('utf-8'))
            except (ValueError, TypeError) as error:
                raise CCInvalidRequestException('Invalid lastKey') from error
            if not isinstance(decoded, dict):
                raise CCInvalidRequestException('Invalid lastKey')
            query['ExclusiveStartKey'] = decoded
        response = self.config.application_table.query(**query)
        evaluated = response.get('LastEvaluatedKey')
        encoded = None if evaluated is None else b64encode(json.dumps(evaluated).encode('utf-8')).decode('utf-8')
        return {
            'items': response.get('Items', []),
            'pagination': {
                'pageSize': page_size,
                'prevLastKey': pagination.get('lastKey'),
                'lastKey': encoded,
            },
        }

    def create_application(
        self,
        compact: str,
        application_id: str,
        *,
        execution_arn: str,
        schedule_name: str,
        workflow_expires_at: str,
        provider_id: str,
        types: list,
        is_renewal: bool,
        created: str,
    ) -> dict:
        """Create the APPLICATION item and six empty SECTION items in one transaction.

        The application is written with no status. ``EnterState`` for ``Started`` is the
        first status writer. A second create of the same id fails the existence condition.
        """
        updated = self.config.current_standard_datetime.isoformat()
        partition_key = self.pk(compact, application_id)
        application = {
            'pk': partition_key,
            'sk': APPLICATION_SK,
            'type': APPLICATION_RECORD_TYPE,
            'compact': compact,
            'applicationId': application_id,
            'version': 0,
            'generation': 1,
            'executionArn': execution_arn,
            'scheduleName': schedule_name,
            'workflowExpiresAt': workflow_expires_at,
            'providerId': provider_id,
            'types': [_string_value(application_type) for application_type in types],
            'isRenewal': is_renewal,
            'created': created,
            'dateOfUpdate': updated,
            'applicantGSIPK': f'{compact}#PROVIDER#{provider_id}',
            'applicantGSISK': application_id,
        }
        transact_items = [
            {
                'Put': {
                    'TableName': self.config.application_table_name,
                    'Item': _serialize_item(application),
                    'ConditionExpression': 'attribute_not_exists(pk)',
                }
            }
        ]
        for section in SectionName:
            transact_items.append(
                {
                    'Put': {
                        'TableName': self.config.application_table_name,
                        'Item': _serialize_item(
                            {
                                'pk': partition_key,
                                'sk': self.section_sk(section),
                                'type': APPLICATION_SECTION_RECORD_TYPE,
                                'compact': compact,
                                'applicationId': application_id,
                                'sectionName': section.value,
                                'data': {},
                                'reviews': [],
                                'dateOfUpdate': updated,
                            }
                        ),
                    }
                }
            )
        try:
            self.config.dynamodb_client.transact_write_items(TransactItems=transact_items)
        except ClientError as error:
            if _condition_failed(error):
                raise CCConflictException('Application already exists') from error
            raise
        return application

    def enter_state(
        self,
        compact: str,
        application_id: str,
        *,
        execution_arn: str,
        state_name: StateName | str,
        entered_time: str,
        task_token: str | None,
        terminal: bool = False,
        reason: str | None = None,
    ) -> dict:
        """Write one state entry and its audit item, or no-op on an exact replay.

        The write is conditioned on the execution ARN and on this entry key not already
        being recorded. An exact replay (same key and task-token hash) returns the
        current item without writing, so a ``pendingAction`` stored by a later request
        is left in place.
        """
        state = _state(state_name)
        definition = STATE_DEFINITIONS[state]
        terminal_write = terminal or definition.terminal
        if not terminal_write and not task_token:
            raise CCInvalidRequestException('A task token is required to enter a wait state')

        current = self.get_application(compact, application_id)
        if current is None:
            raise CCNotFoundException('Application not found')

        entry_key = f'{execution_arn}#{entered_time}#{state.value}'
        updated = self.config.current_standard_datetime.isoformat()
        reopen_request_id = None
        if state is StateName.STAFF_REVIEW:
            reopen_request_id = (current.get('reopenLock') or {}).get('requestId')

        try:
            self.config.dynamodb_client.transact_write_items(
                TransactItems=[
                    self._enter_state_update(
                        compact=compact,
                        application_id=application_id,
                        execution_arn=execution_arn,
                        state=state,
                        entry_key=entry_key,
                        updated=updated,
                        task_token=task_token,
                        terminal_write=terminal_write,
                        reason=reason,
                        actor_sub=actor_sub_for_state(current, state),
                    ),
                    {
                        'Put': {
                            'TableName': self.config.application_table_name,
                            'Item': _serialize_item(
                                self._transition_item(
                                    compact=compact,
                                    application_id=application_id,
                                    state=state,
                                    entered_time=entered_time,
                                    execution_arn=execution_arn,
                                    from_state=current.get('stateName'),
                                    updated=updated,
                                )
                            ),
                        }
                    },
                ]
            )
        except ClientError as error:
            if not _condition_failed(error):
                raise
            latest = self.get_application(compact, application_id)
            if (
                latest
                and latest.get('lastEnteredKey') == entry_key
                and _recorded_token_matches(latest, task_token, terminal=terminal_write)
            ):
                return latest
            raise CCConflictException('The execution does not match this application state entry') from error

        if reopen_request_id:
            self._remove_matching_reopen_lock(compact, application_id, str(reopen_request_id))
        stored = self.get_application(compact, application_id)
        if stored is None:
            raise CCNotFoundException('Application not found')
        return stored

    def _write_application(
        self,
        compact: str,
        application_id: str,
        *,
        update_expression: str,
        condition: str,
        values: Mapping,
        conflict_message: str,
        accept: Callable[[Mapping], bool] | None = None,
    ) -> dict:
        """Apply one conditional update to the APPLICATION item and return the stored item.

        The caller supplies the expression, condition, and values. On a condition failure,
        a re-read is returned when ``accept`` says this write already landed.
        """
        try:
            self.config.dynamodb_client.update_item(
                TableName=self.config.application_table_name,
                Key=_serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
                UpdateExpression=update_expression,
                ConditionExpression=condition,
                ExpressionAttributeValues=_attribute_values(values),
            )
        except ClientError as error:
            if not _is_conflict(error):
                raise
            if accept is not None:
                latest = self.get_application(compact, application_id)
                if latest is not None and accept(latest):
                    return latest
            raise CCConflictException(conflict_message) from error
        stored = self.get_application(compact, application_id)
        if stored is None:
            raise CCNotFoundException('Application not found')
        return stored

    def acquire_reopen_lock(self, compact: str, application_id: str, request_id: str) -> dict:
        """Hold the application for one reopen request.

        The same request id is a no-op. A different request id conflicts. The lock keeps the
        expiry chosen for the new generation so a retry starts the same execution.
        """
        current = self.get_application(compact, application_id)
        if current is None:
            raise CCNotFoundException('Application not found')
        existing = current.get('reopenLock') or {}
        if existing.get('requestId') == request_id:
            return current
        if existing:
            raise CCConflictException('Application reopen is locked')

        lock = {
            'requestId': request_id,
            'oldGeneration': int(current.get('generation') or 1),
            'workflowExpiresAt': (self.config.current_standard_datetime + workflow_lifetime()).isoformat(),
        }
        if current.get('executionArn'):
            lock['oldExecutionArn'] = current['executionArn']
        return self._write_application(
            compact,
            application_id,
            update_expression='SET reopenLock = :lock, dateOfUpdate = :now ADD version :one',
            condition='attribute_not_exists(reopenLock) OR reopenLock.requestId = :requestId',
            values={':lock': lock, ':requestId': request_id, ':now': self._timestamp(), ':one': 1},
            conflict_message='Application reopen is locked',
            accept=lambda item: (item.get('reopenLock') or {}).get('requestId') == request_id,
        )

    def claim_reopen_deactivation(self, compact: str, application_id: str, request_id: str, actor_sub: str) -> dict:
        """Store the deactivation callback while this reopen request holds the lock."""
        current = self.get_application(compact, application_id)
        if current is None:
            raise CCNotFoundException('Application not found')
        if (current.get('reopenLock') or {}).get('requestId') != request_id:
            raise CCConflictException('Application reopen is locked')
        pending = current.get('pendingAction') or {}
        if pending.get('requestId') == request_id:
            return current
        if pending:
            raise CCConflictException('A transition is already pending')
        if not current.get('stateName'):
            raise CCInvalidRequestException('Application has no state')

        pending_action = {
            'requestId': request_id,
            'action': WorkflowAction.ADMIN_DEACTIVATE.value,
            'actorSub': actor_sub,
            'expectedStateName': current['stateName'],
            'expectedVersion': int(current.get('version') or 0),
            'createdAt': self._timestamp(),
            'attempts': 0,
        }
        if current.get('lastEnteredKey'):
            pending_action['expectedLastEnteredKey'] = current['lastEnteredKey']
        return self._write_application(
            compact,
            application_id,
            update_expression='SET pendingAction = :pendingAction, dateOfUpdate = :now ADD version :one',
            condition='reopenLock.requestId = :requestId AND attribute_not_exists(pendingAction)',
            values={
                ':pendingAction': pending_action,
                ':requestId': request_id,
                ':now': self._timestamp(),
                ':one': 1,
            },
            conflict_message='Application reopen is locked',
            accept=lambda item: (item.get('pendingAction') or {}).get('requestId') == request_id,
        )

    def commit_reopen_generation(
        self,
        compact: str,
        application_id: str,
        request_id: str,
        new_execution_arn: str,
        schedule_name: str,
        workflow_expires_at: str,
    ) -> int:
        """Point the application at the next generation without changing its status or reviews.

        Reviewer assignments, embedded reviews, and SECTION items stay as they are. ``EnterState``
        writes the new staff-review status and clears the matching lock.
        """
        current = self.get_application(compact, application_id)
        if current is None:
            raise CCNotFoundException('Application not found')
        if (current.get('reopenLock') or {}).get('requestId') != request_id:
            raise CCConflictException('Application reopen is locked')
        if current.get('executionArn') == new_execution_arn:
            return int(current.get('generation') or 1)

        values = {
            ':arn': new_execution_arn,
            ':schedule': schedule_name,
            ':expires': workflow_expires_at,
            ':requestId': request_id,
            ':now': self._timestamp(),
            ':one': 1,
        }
        old_arn = (current.get('reopenLock') or {}).get('oldExecutionArn')
        if old_arn:
            condition = 'reopenLock.requestId = :requestId AND executionArn = :oldArn'
            values[':oldArn'] = old_arn
        else:
            condition = 'reopenLock.requestId = :requestId AND attribute_not_exists(executionArn)'
        stored = self._write_application(
            compact,
            application_id,
            update_expression=(
                'SET executionArn = :arn, scheduleName = :schedule, workflowExpiresAt = :expires, '
                'dateOfUpdate = :now '
                'REMOVE taskToken, taskTokenHash, pendingAction, completed, deactivationReason, '
                'lastExecutionError, lastEnteredKey '
                'ADD generation :one, version :one'
            ),
            condition=condition,
            values=values,
            conflict_message='Application generation changed during reopen',
            accept=lambda item: item.get('executionArn') == new_execution_arn,
        )
        return int(stored.get('generation') or 1)

    def release_reopen_lock_on_failure(self, compact: str, application_id: str, request_id: str) -> bool:
        """Drop the lock when this request still holds it and the new generation was not committed."""
        current = self.get_application(compact, application_id)
        if current is None:
            return False
        lock = current.get('reopenLock') or {}
        if lock.get('requestId') != request_id:
            return False
        old_arn = lock.get('oldExecutionArn')
        if old_arn and current.get('executionArn') != old_arn:
            return False
        values = {':requestId': request_id}
        if old_arn:
            condition = 'reopenLock.requestId = :requestId AND executionArn = :oldArn'
            values[':oldArn'] = old_arn
        else:
            condition = 'reopenLock.requestId = :requestId AND attribute_not_exists(executionArn)'
        try:
            self.config.dynamodb_client.update_item(
                TableName=self.config.application_table_name,
                Key=_serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
                UpdateExpression='REMOVE reopenLock SET dateOfUpdate = :now ADD version :one',
                ConditionExpression=condition,
                ExpressionAttributeValues=_attribute_values({**values, ':now': self._timestamp(), ':one': 1}),
            )
        except ClientError as error:
            if _is_conflict(error):
                return False
            raise
        return True

    def mark_deactivated_by_reconciler(
        self,
        compact: str,
        application_id: str,
        *,
        execution_arn: str,
        generation: int,
        reason: str,
        last_execution_error: str | None,
    ) -> str:
        """Deactivate the current generation when its execution has stopped outside the graph.

        Returns ``applied`` when this call wrote the deactivation, ``already`` when that
        reason is already recorded, and ``stale`` when a newer generation or a finished
        application must be left alone.
        """
        current = self.get_application(compact, application_id)
        if not _reconciler_targets(current, execution_arn, generation):
            return 'stale'
        if _already_reconciled(current, reason):
            return 'already'

        updated = self._timestamp()
        state = StateName.DEACTIVATED
        entry_key = f'{execution_arn}#{updated}#{state.value}'
        try:
            self.config.dynamodb_client.transact_write_items(
                TransactItems=[
                    self._reconciler_update(
                        compact=compact,
                        application_id=application_id,
                        execution_arn=execution_arn,
                        generation=generation,
                        reason=reason,
                        last_execution_error=last_execution_error,
                        entry_key=entry_key,
                        updated=updated,
                    ),
                    {
                        'Put': {
                            'TableName': self.config.application_table_name,
                            'Item': _serialize_item(
                                self._transition_item(
                                    compact=compact,
                                    application_id=application_id,
                                    state=state,
                                    entered_time=updated,
                                    execution_arn=execution_arn,
                                    from_state=current.get('stateName'),
                                    updated=updated,
                                )
                            ),
                            'ConditionExpression': 'attribute_not_exists(pk)',
                        }
                    },
                ]
            )
        except ClientError as error:
            if not _condition_failed(error):
                raise
            latest = self.get_application(compact, application_id)
            if _already_reconciled(latest, reason) and _reconciler_targets(latest, execution_arn, generation):
                return 'already'
            return 'stale'
        return 'applied'

    def _reconciler_update(
        self,
        *,
        compact: str,
        application_id: str,
        execution_arn: str,
        generation: int,
        reason: str,
        last_execution_error: str | None,
        entry_key: str,
        updated: str,
    ) -> dict:
        status = ApplicationStatus.DEACTIVATED.value
        set_parts = [
            '#status = :status',
            'stateName = :stateName',
            'lastEnteredKey = :key',
            'statusGSIPK = :statusGSIPK',
            'statusGSISK = :statusGSISK',
            'completed = :completed',
            'deactivationReason = :reason',
            'dateOfUpdate = :updated',
        ]
        values = {
            ':status': status,
            ':stateName': StateName.DEACTIVATED.value,
            ':key': entry_key,
            ':arn': execution_arn,
            ':generation': generation,
            ':approved': ApplicationStatus.APPROVED.value,
            ':rejected': ApplicationStatus.REJECTED.value,
            ':deactivated': ApplicationStatus.DEACTIVATED.value,
            ':statusGSIPK': f'{compact}#STATUS#{status}',
            ':statusGSISK': f'{updated}#{application_id}',
            ':completed': updated,
            ':reason': reason,
            ':updated': updated,
            ':one': 1,
        }
        if last_execution_error:
            set_parts.append('lastExecutionError = :lastExecutionError')
            values[':lastExecutionError'] = last_execution_error
        expression = (
            f'SET {", ".join(set_parts)} '
            'REMOVE pendingAction, taskToken, taskTokenHash, actorGSIPK, actorGSISK '
            'ADD version :one'
        )
        return {
            'Update': {
                'TableName': self.config.application_table_name,
                'Key': _serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
                'UpdateExpression': expression,
                'ConditionExpression': (
                    'executionArn = :arn AND generation = :generation AND ('
                    'attribute_not_exists(#status) OR '
                    'NOT (#status IN (:approved, :rejected, :deactivated)) OR '
                    'reopenLock.oldExecutionArn = :arn)'
                ),
                'ExpressionAttributeNames': {'#status': 'status'},
                'ExpressionAttributeValues': _attribute_values(values),
            }
        }

    def _enter_state_update(
        self,
        *,
        compact: str,
        application_id: str,
        execution_arn: str,
        state: StateName,
        entry_key: str,
        updated: str,
        task_token: str | None,
        terminal_write: bool,
        reason: str | None,
        actor_sub: str | None,
    ) -> dict:
        definition = STATE_DEFINITIONS[state]
        status = definition.status.value
        set_parts = [
            '#status = :status',
            'stateName = :stateName',
            'lastEnteredKey = :key',
            'statusGSIPK = :statusGSIPK',
            'statusGSISK = :statusGSISK',
            'dateOfUpdate = :updated',
        ]
        remove_parts = ['pendingAction']
        values = {
            ':status': status,
            ':stateName': state.value,
            ':key': entry_key,
            ':arn': execution_arn,
            ':statusGSIPK': f'{compact}#STATUS#{status}',
            ':statusGSISK': f'{updated}#{application_id}',
            ':updated': updated,
            ':one': 1,
        }
        if terminal_write:
            remove_parts.extend(['taskToken', 'taskTokenHash', 'actorGSIPK', 'actorGSISK'])
            set_parts.append('completed = :completed')
            values[':completed'] = updated
            if reason is not None:
                set_parts.append('deactivationReason = :reason')
                values[':reason'] = reason
        else:
            set_parts.extend(['taskToken = :taskToken', 'taskTokenHash = :taskTokenHash'])
            values[':taskToken'] = task_token
            values[':taskTokenHash'] = task_token_hash(task_token)
            if actor_sub:
                set_parts.extend(['actorGSIPK = :actorGSIPK', 'actorGSISK = :actorGSISK'])
                values[':actorGSIPK'] = f'{compact}#ACTOR#{actor_sub}'
                values[':actorGSISK'] = f'{status}#{application_id}'
            else:
                remove_parts.extend(['actorGSIPK', 'actorGSISK'])

        expression = f'SET {", ".join(set_parts)} REMOVE {", ".join(dict.fromkeys(remove_parts))} ADD version :one'
        return {
            'Update': {
                'TableName': self.config.application_table_name,
                'Key': _serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
                'UpdateExpression': expression,
                'ConditionExpression': (
                    'executionArn = :arn AND (attribute_not_exists(lastEnteredKey) OR lastEnteredKey <> :key)'
                ),
                'ExpressionAttributeNames': {'#status': 'status'},
                'ExpressionAttributeValues': _attribute_values(values),
            }
        }

    def _transition_item(
        self,
        *,
        compact: str,
        application_id: str,
        state: StateName,
        entered_time: str,
        execution_arn: str,
        from_state: str | None,
        updated: str,
    ) -> dict:
        item = {
            'pk': self.pk(compact, application_id),
            'sk': self.transition_sk(entered_time, state),
            'type': APPLICATION_TRANSITION_RECORD_TYPE,
            'compact': compact,
            'applicationId': application_id,
            'toState': state.value,
            'enteredTime': entered_time,
            'executionArn': execution_arn,
            'dateOfUpdate': updated,
        }
        if from_state:
            item['fromState'] = str(from_state)
        return item

    def _remove_matching_reopen_lock(self, compact: str, application_id: str, request_id: str) -> None:
        """Clear a staff-review reopen lock only when its request id is still the one observed."""
        try:
            self.config.dynamodb_client.update_item(
                TableName=self.config.application_table_name,
                Key=_serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
                UpdateExpression='REMOVE reopenLock',
                ConditionExpression='reopenLock.requestId = :requestId',
                ExpressionAttributeValues=_attribute_values({':requestId': request_id}),
            )
        except ClientError as error:
            if error.response['Error']['Code'] == 'ConditionalCheckFailedException':
                return
            raise

    def patch_section(
        self,
        compact: str,
        application_id: str,
        section: SectionName | str,
        data: Mapping,
        *,
        actor_provider_id: str,
    ) -> ApplicationSnapshot:
        """Merge fields into one section while the applicant is allowed to edit.

        The section write is conditioned on the ``updated`` value that was read.
        The application write requires an applicant-editable state, no pending action,
        no reopen lock, and the applicant's provider id. It bumps ``version``.
        """
        section_name = section if isinstance(section, SectionName) else SectionName(section)
        current = self._get_keyed_item(compact, application_id, self.section_sk(section_name))
        if current is None:
            raise CCNotFoundException('Application section not found')

        updated = self._timestamp()
        merged = _merge_section_data(current.get('data'), data)
        previous_updated = current.get('updated')
        if previous_updated is None:
            section_condition = 'attribute_not_exists(updated)'
            section_values = {':data': merged, ':now': updated}
        else:
            section_condition = 'updated = :previousUpdated'
            section_values = {':data': merged, ':now': updated, ':previousUpdated': previous_updated}

        state_placeholders = []
        application_values = {':now': updated, ':one': 1, ':pid': actor_provider_id}
        for index, state_name in enumerate(sorted(APPLICANT_EDITABLE_STATES, key=lambda state: state.value)):
            placeholder = f':editableState{index}'
            state_placeholders.append(placeholder)
            application_values[placeholder] = state_name.value

        try:
            self.config.dynamodb_client.transact_write_items(
                TransactItems=[
                    {
                        'Update': {
                            'TableName': self.config.application_table_name,
                            'Key': _serialize_item(
                                {'pk': self.pk(compact, application_id), 'sk': self.section_sk(section_name)}
                            ),
                            'UpdateExpression': 'SET #data = :data, updated = :now',
                            'ConditionExpression': section_condition,
                            'ExpressionAttributeNames': {'#data': 'data'},
                            'ExpressionAttributeValues': _attribute_values(section_values),
                        }
                    },
                    {
                        'Update': {
                            'TableName': self.config.application_table_name,
                            'Key': _serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
                            'UpdateExpression': 'SET dateOfUpdate = :now ADD version :one',
                            'ConditionExpression': (
                                f'stateName IN ({", ".join(state_placeholders)}) '
                                'AND attribute_not_exists(pendingAction) '
                                'AND attribute_not_exists(reopenLock) '
                                'AND providerId = :pid'
                            ),
                            'ExpressionAttributeValues': _attribute_values(application_values),
                        }
                    },
                ]
            )
        except ClientError as error:
            if _is_conflict(error):
                raise CCConflictException('Section update was rejected') from error
            raise
        return self.get_snapshot(compact, application_id)

    def assign_reviewers(
        self,
        compact: str,
        application_id: str,
        request: Mapping,
        *,
        expected_version: int,
    ) -> ReviewerAssignmentResult:
        """Assign or reassign reviewers and create their pending review shells.

        Each changed role gets a new assignment id. Previous review objects stay on the
        application and on every section. The write is fenced by version, status, and
        the first/second distinctness rule.
        """
        application = self.get_application(compact, application_id)
        if application is None:
            raise CCNotFoundException('Application not found')

        resulting = {
            ActorRole.FIRST_REVIEWER: _resulting_reviewer_sub(request, application, 'firstReviewerSub'),
            ActorRole.SECOND_REVIEWER: _resulting_reviewer_sub(request, application, 'secondReviewerSub'),
            ActorRole.FINAL_REVIEWER: _resulting_reviewer_sub(request, application, 'finalReviewerSub'),
        }
        validate_reviewer_assignment(
            resulting[ActorRole.FIRST_REVIEWER],
            resulting[ActorRole.SECOND_REVIEWER],
            resulting[ActorRole.FINAL_REVIEWER],
        )

        updated = self._timestamp()
        changes = []
        for role, (sub_field, _assignment_field, first_field, last_field, _reviewer_type) in _ROLE_FIELDS.items():
            if sub_field not in request or not request.get(sub_field):
                continue
            new_sub = str(request[sub_field])
            if new_sub == application.get(sub_field):
                continue
            changes.append(
                {
                    'role': role,
                    'sub': new_sub,
                    'assignment_id': str(uuid4()),
                    'first_name': request.get(first_field),
                    'last_name': request.get(last_field),
                    'sub_field': sub_field,
                    'assignment_field': _assignment_field,
                    'first_field': first_field,
                    'last_field': last_field,
                    'reviewer_type': _reviewer_type,
                }
            )

        if not changes:
            snapshot = self.get_snapshot(compact, application_id)
            return ReviewerAssignmentResult(
                snapshot=snapshot,
                all_reviewers_set=_all_reviewers_set(snapshot.application),
            )

        application_reviews = [
            _review_shell(
                assignment_id=change['assignment_id'],
                reviewer_type=change['reviewer_type'],
                sub=change['sub'],
                first_name=change['first_name'],
                last_name=change['last_name'],
                assigned_date=updated,
                section=False,
            )
            for change in changes
        ]
        section_reviews = [
            _review_shell(
                assignment_id=change['assignment_id'],
                reviewer_type=change['reviewer_type'],
                sub=change['sub'],
                first_name=change['first_name'],
                last_name=change['last_name'],
                assigned_date=updated,
                section=True,
            )
            for change in changes
        ]
        try:
            self.config.dynamodb_client.transact_write_items(
                TransactItems=[
                    self._assign_application_update(
                        compact=compact,
                        application_id=application_id,
                        application=application,
                        changes=changes,
                        new_reviews=application_reviews,
                        expected_version=expected_version,
                        updated=updated,
                    ),
                    *[
                        self._append_section_reviews_update(
                            compact=compact,
                            application_id=application_id,
                            section=section,
                            new_reviews=section_reviews,
                            updated=updated,
                        )
                        for section in SectionName
                    ],
                ]
            )
        except ClientError as error:
            if _is_conflict(error):
                raise CCConflictException('Reviewer assignment was rejected') from error
            raise

        snapshot = self.get_snapshot(compact, application_id)
        return ReviewerAssignmentResult(snapshot=snapshot, all_reviewers_set=_all_reviewers_set(snapshot.application))

    @staticmethod
    def locate_active_review(application_item: Mapping, role: ActorRole | str) -> dict | None:
        return _locate_active_review(application_item, role)

    @staticmethod
    def locate_active_section_review(
        section_item: Mapping, application_item: Mapping, role: ActorRole | str
    ) -> dict | None:
        return _locate_active_section_review(section_item, application_item, role)

    def save_section_review(
        self,
        compact: str,
        application_id: str,
        section: SectionName | str,
        role: ActorRole | str,
        caller_sub: str,
        section_status: ReviewSectionStatus | str,
        notes: Mapping | None = None,
    ) -> ApplicationSnapshot:
        """Save the caller's active section review for one role.

        The section condition keeps the write on that assignment. The application condition
        allows only the review node and committee node for the role, and only that role's
        current assignee.
        """
        actor_role = _actor_role(role)
        section_name = section if isinstance(section, SectionName) else SectionName(section)
        status = section_status.value if isinstance(section_status, ReviewSectionStatus) else str(section_status)
        application = self.get_application(compact, application_id)
        if application is None:
            raise CCNotFoundException('Application not found')
        section_item = self._get_keyed_item(compact, application_id, self.section_sk(section_name))
        if section_item is None:
            raise CCNotFoundException('Application section not found')

        sub_field, assignment_field, _first, _last, reviewer_type = _ROLE_FIELDS[actor_role]
        located = _matching_review(
            section_item.get('reviews'),
            reviewer_type=reviewer_type.value,
            sub=application.get(sub_field),
            assignment_id=application.get(assignment_field),
        )
        if located is None:
            raise CCInvalidRequestException('Active section review is missing')
        index, _review = located
        assignment_id = application.get(assignment_field)
        updated = self._timestamp()
        review_node, committee_node = reviewer_edit_states(actor_role)
        set_parts = [
            f'reviews[{index}].reviewerSelectedApplicationSectionStatus = :sectionStatus',
            f'reviews[{index}].reviewCompletionDate = :now',
        ]
        section_values = {':sectionStatus': status, ':now': updated, ':assignmentId': assignment_id}
        for note_field in ('notesForApplicant', 'notesForReviewers'):
            if notes and note_field in notes and notes[note_field] is not None:
                set_parts.append(f'reviews[{index}].{note_field} = :{note_field}')
                section_values[f':{note_field}'] = notes[note_field]
        application_values = {
            ':now': updated,
            ':one': 1,
            ':callerSub': caller_sub,
            ':assignmentId': assignment_id,
            ':reviewNode': review_node.value,
            ':committeeNode': committee_node.value,
        }

        try:
            self.config.dynamodb_client.transact_write_items(
                TransactItems=[
                    {
                        'Update': {
                            'TableName': self.config.application_table_name,
                            'Key': _serialize_item(
                                {'pk': self.pk(compact, application_id), 'sk': self.section_sk(section_name)}
                            ),
                            'UpdateExpression': f'SET {", ".join(set_parts)}',
                            'ConditionExpression': f'reviews[{index}].assignmentId = :assignmentId',
                            'ExpressionAttributeValues': _attribute_values(section_values),
                        }
                    },
                    {
                        'Update': {
                            'TableName': self.config.application_table_name,
                            'Key': _serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
                            'UpdateExpression': 'SET dateOfUpdate = :now ADD version :one',
                            'ConditionExpression': (
                                'stateName IN (:reviewNode, :committeeNode) '
                                'AND attribute_not_exists(pendingAction) '
                                f'AND {sub_field} = :callerSub '
                                f'AND {assignment_field} = :assignmentId'
                            ),
                            'ExpressionAttributeValues': _attribute_values(application_values),
                        }
                    },
                ]
            )
        except ClientError as error:
            if _is_conflict(error):
                raise CCConflictException('Section review was rejected') from error
            raise
        return self.get_snapshot(compact, application_id)

    def require_complete_reviews(self, snapshot: ApplicationSnapshot, role: ActorRole | str) -> None:
        """Require every current section review for this role to be approved or rejected."""
        for section_name in SectionName:
            review = _locate_active_section_review(snapshot.sections[section_name], snapshot.application, role)
            status = None if review is None else review.get('reviewerSelectedApplicationSectionStatus')
            if status in (None, ReviewSectionStatus.PENDING.value):
                raise CCInvalidRequestException('Section reviews are incomplete')

    def begin_transition(
        self,
        compact: str,
        application_id: str,
        *,
        expected_version: int,
        expected_state_name: StateName | str,
        pending_action: Mapping,
        application_review_update: Mapping | None = None,
        extra_set: Mapping | None = None,
    ) -> dict:
        """Claim a transition by storing ``pendingAction`` and bumping ``version``.

        The condition is the fencing check: the expected version and state, and no
        pending action or reopen lock. A losing caller gets a conflict.
        """
        state_name = _state(expected_state_name)
        updated = self._timestamp()
        values = {
            ':version': expected_version,
            ':stateName': state_name.value,
            ':pendingAction': dict(pending_action),
            ':now': updated,
            ':one': 1,
        }
        set_parts = ['pendingAction = :pendingAction', 'dateOfUpdate = :now']
        if application_review_update is not None:
            application = self.get_application(compact, application_id)
            if application is None:
                raise CCNotFoundException('Application not found')

        if application_review_update is not None:
            self._add_application_review_update(
                application=application,
                review_update=application_review_update,
                updated=updated,
                set_parts=set_parts,
                values=values,
            )

        applied_extra = dict(extra_set or {})
        if (
            _string_value(pending_action.get('action')) == WorkflowAction.SUBMIT.value
            and 'submitted' not in applied_extra
        ):
            applied_extra['submitted'] = updated
        for index, (field_name, field_value) in enumerate(applied_extra.items()):
            placeholder = f':extra{index}'
            set_parts.append(f'{field_name} = {placeholder}')
            values[placeholder] = field_value

        return self._write_application(
            compact,
            application_id,
            update_expression=f'SET {", ".join(set_parts)} ADD version :one',
            condition=(
                'version = :version AND stateName = :stateName '
                'AND attribute_not_exists(pendingAction) AND attribute_not_exists(reopenLock)'
            ),
            values=values,
            conflict_message='Transition was rejected',
        )

    def clear_pending_action(self, compact: str, application_id: str, request_id: str) -> bool:
        """Remove ``pendingAction`` only when its request id still matches."""
        try:
            self.config.dynamodb_client.update_item(
                TableName=self.config.application_table_name,
                Key=_serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
                UpdateExpression='REMOVE pendingAction SET dateOfUpdate = :now ADD version :one',
                ConditionExpression='pendingAction.requestId = :requestId',
                ExpressionAttributeValues=_attribute_values(
                    {':requestId': request_id, ':now': self._timestamp(), ':one': 1}
                ),
            )
        except ClientError as error:
            if _is_conflict(error):
                return False
            raise
        return True

    def record_delivery_attempt(self, compact: str, application_id: str, request_id: str) -> dict:
        """Increment ``pendingAction.attempts`` for the matching request."""
        return self._write_application(
            compact,
            application_id,
            update_expression=(
                'SET pendingAction.attempts = if_not_exists(pendingAction.attempts, :zero) + :one, '
                'dateOfUpdate = :now ADD version :one'
            ),
            condition='pendingAction.requestId = :requestId',
            values={':requestId': request_id, ':zero': 0, ':one': 1, ':now': self._timestamp()},
            conflict_message='Pending action does not match this request',
        )

    def put_request_record(
        self,
        compact: str,
        application_id: str,
        request_id: str,
        *,
        action: WorkflowAction | str,
        result: Mapping | None = None,
        ttl: int,
        created_at: str | None = None,
        actor_sub: str | None = None,
    ) -> dict:
        """Store an idempotency record. A second put of the same request id conflicts."""
        item = {
            'pk': self.pk(compact, application_id),
            'sk': self.request_sk(request_id),
            'type': APPLICATION_REQUEST_RECORD_TYPE,
            'compact': compact,
            'applicationId': application_id,
            'requestId': request_id,
            'action': _string_value(action),
            'createdAt': created_at or self._timestamp(),
            'ttl': ttl,
        }
        if actor_sub is not None:
            item['actorSub'] = actor_sub
        if result is not None:
            item['result'] = dict(result)
        try:
            self.config.dynamodb_client.put_item(
                TableName=self.config.application_table_name,
                Item=_serialize_item(item),
                ConditionExpression='attribute_not_exists(pk)',
            )
        except ClientError as error:
            if _is_conflict(error):
                raise CCConflictException('Request record already exists') from error
            raise
        return item

    def get_request_record(self, compact: str, application_id: str, request_id: str) -> dict | None:
        """Return the request idempotency item, or None when it does not exist."""
        return self._get_keyed_item(compact, application_id, self.request_sk(request_id))

    def _timestamp(self) -> str:
        return self.config.current_standard_datetime.isoformat()

    def _get_keyed_item(self, compact: str, application_id: str, sort_key: str) -> dict | None:
        response = self.config.dynamodb_client.get_item(
            TableName=self.config.application_table_name,
            Key=_serialize_item({'pk': self.pk(compact, application_id), 'sk': sort_key}),
            ConsistentRead=True,
        )
        item = response.get('Item')
        if not item:
            return None
        return _deserialize_item(item)

    def _assign_application_update(
        self,
        *,
        compact: str,
        application_id: str,
        application: Mapping,
        changes: list[dict],
        new_reviews: list[dict],
        expected_version: int,
        updated: str,
    ) -> dict:
        values = {
            ':version': expected_version,
            ':one': 1,
            ':updated': updated,
            ':emptyReviews': [],
            ':newReviews': new_reviews,
        }
        set_parts = [
            'dateOfUpdate = :updated',
            'reviews = list_append(if_not_exists(reviews, :emptyReviews), :newReviews)',
        ]
        remove_parts = []
        changed_roles = {change['role'] for change in changes}
        first_change = None
        second_change = None
        for change in changes:
            set_parts.append(f'{change["sub_field"]} = :{change["sub_field"]}')
            set_parts.append(f'{change["assignment_field"]} = :{change["assignment_field"]}')
            values[f':{change["sub_field"]}'] = change['sub']
            values[f':{change["assignment_field"]}'] = change['assignment_id']
            if change['first_name']:
                set_parts.append(f'{change["first_field"]} = :{change["first_field"]}')
                values[f':{change["first_field"]}'] = change['first_name']
            else:
                remove_parts.append(change['first_field'])
            if change['last_name']:
                set_parts.append(f'{change["last_field"]} = :{change["last_field"]}')
                values[f':{change["last_field"]}'] = change['last_name']
            else:
                remove_parts.append(change['last_field'])
            if change['role'] is ActorRole.FIRST_REVIEWER:
                first_change = change
            elif change['role'] is ActorRole.SECOND_REVIEWER:
                second_change = change

        state = _state(application['stateName']) if application.get('stateName') else None
        if state is not None and STATE_DEFINITIONS[state].actor_role in changed_roles:
            actor_role = STATE_DEFINITIONS[state].actor_role
            actor_sub = next(change['sub'] for change in changes if change['role'] is actor_role)
            status = application.get('status')
            if actor_sub and status:
                set_parts.extend(['actorGSIPK = :actorGSIPK', 'actorGSISK = :actorGSISK'])
                values[':actorGSIPK'] = f'{compact}#ACTOR#{actor_sub}'
                values[':actorGSISK'] = f'{status}#{application_id}'

        status_placeholders = []
        for index, status in enumerate(_ASSIGNABLE_STATUSES):
            placeholder = f':assignStatus{index}'
            status_placeholders.append(placeholder)
            values[placeholder] = status.value
        condition = (
            'version = :version AND attribute_not_exists(pendingAction) '
            f'AND #status IN ({", ".join(status_placeholders)})'
        )
        if first_change is not None and second_change is None:
            values[':distinctSub'] = first_change['sub']
            condition += ' AND (attribute_not_exists(secondReviewerSub) OR secondReviewerSub <> :distinctSub)'
        elif second_change is not None and first_change is None:
            values[':distinctSub'] = second_change['sub']
            condition += ' AND (attribute_not_exists(firstReviewerSub) OR firstReviewerSub <> :distinctSub)'

        expression = f'SET {", ".join(set_parts)}'
        if remove_parts:
            expression += f' REMOVE {", ".join(remove_parts)}'
        expression += ' ADD version :one'
        return {
            'Update': {
                'TableName': self.config.application_table_name,
                'Key': _serialize_item({'pk': self.pk(compact, application_id), 'sk': APPLICATION_SK}),
                'UpdateExpression': expression,
                'ConditionExpression': condition,
                'ExpressionAttributeNames': {'#status': 'status'},
                'ExpressionAttributeValues': _attribute_values(values),
            }
        }

    def _append_section_reviews_update(
        self,
        *,
        compact: str,
        application_id: str,
        section: SectionName,
        new_reviews: list[dict],
        updated: str,
    ) -> dict:
        return {
            'Update': {
                'TableName': self.config.application_table_name,
                'Key': _serialize_item({'pk': self.pk(compact, application_id), 'sk': self.section_sk(section)}),
                'UpdateExpression': (
                    'SET reviews = list_append(if_not_exists(reviews, :emptyReviews), :newReviews), updated = :updated'
                ),
                'ExpressionAttributeValues': _attribute_values(
                    {':emptyReviews': [], ':newReviews': new_reviews, ':updated': updated}
                ),
            }
        }

    def _add_application_review_update(
        self,
        *,
        application: Mapping,
        review_update: Mapping,
        updated: str,
        set_parts: list[str],
        values: dict,
    ) -> None:
        role = _actor_role(review_update['role'])
        sub_field, assignment_field, first_field, last_field, reviewer_type = _ROLE_FIELDS[role]
        located = _matching_review(
            application.get('reviews'),
            reviewer_type=reviewer_type.value,
            sub=application.get(sub_field),
            assignment_id=application.get(assignment_field),
        )
        if located is None:
            shell = _review_shell(
                assignment_id=str(application.get(assignment_field) or uuid4()),
                reviewer_type=reviewer_type,
                sub=str(application.get(sub_field) or ''),
                first_name=application.get(first_field),
                last_name=application.get(last_field),
                assigned_date=updated,
                section=False,
            )
            if review_update.get('reviewerSelectedApplicationStatus'):
                shell['reviewerSelectedApplicationStatus'] = _string_value(
                    review_update['reviewerSelectedApplicationStatus']
                )
            for note_field in ('notesForApplicant', 'notesForReviewers'):
                if review_update.get(note_field):
                    shell[note_field] = review_update[note_field]
            shell['reviewCompletionDate'] = updated
            set_parts.append('reviews = list_append(if_not_exists(reviews, :emptyReviews), :newApplicationReview)')
            values[':emptyReviews'] = []
            values[':newApplicationReview'] = [shell]
            return

        index, _review = located
        if review_update.get('reviewerSelectedApplicationStatus'):
            set_parts.append(f'reviews[{index}].reviewerSelectedApplicationStatus = :selectedStatus')
            values[':selectedStatus'] = _string_value(review_update['reviewerSelectedApplicationStatus'])
        for note_field in ('notesForApplicant', 'notesForReviewers'):
            if note_field in review_update and review_update[note_field] is not None:
                set_parts.append(f'reviews[{index}].{note_field} = :{note_field}')
                values[f':{note_field}'] = review_update[note_field]
        set_parts.append(f'reviews[{index}].reviewCompletionDate = :reviewCompleted')
        values[':reviewCompleted'] = updated


def _resulting_reviewer_sub(request: Mapping, application: Mapping, field: str):
    """Return the sub that will be stored for one reviewer role.

    A missing or null request field keeps the current assignment. Validation has to see
    that stored value, not the null that arrived on the request.
    """
    if field in request and request[field]:
        return str(request[field])
    return application.get(field)


def _all_reviewers_set(application: Mapping) -> bool:
    return all(application.get(field) for field in _REVIEWER_SUB_FIELDS.values())
