"""DynamoDB access for practitioner applications.

Transactions use the low-level DynamoDB client and ``TypeSerializer`` / ``TypeDeserializer``.
The resource ``Table`` API cannot express ``TransactGetItems`` or ``TransactWriteItems``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
from common_lambdas.exceptions import CCConflictException, CCInvalidRequestException, CCNotFoundException

from cc_common.applicants.application_state import (
    STATE_DEFINITIONS,
    ActorRole,
    SectionName,
    StateName,
)

APPLICATION_SK = 'APPLICATION'
APPLICATION_RECORD_TYPE = 'application'
APPLICATION_SECTION_RECORD_TYPE = 'applicationSection'
APPLICATION_TRANSITION_RECORD_TYPE = 'applicationTransition'

_REVIEWER_SUB_FIELDS = {
    ActorRole.FIRST_REVIEWER: 'firstReviewerSub',
    ActorRole.SECOND_REVIEWER: 'secondReviewerSub',
    ActorRole.FINAL_REVIEWER: 'finalReviewerSub',
}

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


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
