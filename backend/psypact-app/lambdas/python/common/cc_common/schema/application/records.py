# ruff: noqa: N801, N802, N815, ARG002  invalid-name unused-argument
"""DynamoDB item schemas for the application table.

``pk`` and ``sk`` are generated on dump and removed on load, matching BaseRecordSchema.
"""

from common_lambdas.config import config
from common_lambdas.data_model.schema.base_record import BaseRecordSchema
from common_lambdas.data_model.schema.common import CCDataClass
from marshmallow import ValidationError, post_load, pre_dump
from marshmallow.fields import AwareDateTime, Boolean, Dict, Integer, List, Nested, Raw, String
from marshmallow.validate import OneOf

from cc_common.application_state import ApplicationStatus, ApplicationType, SectionName, StateName, WorkflowAction
from cc_common.schema.application.reviews import ApplicationReviewSchema, ApplicationSectionReviewSchema
from cc_common.schema.application.sections import SECTION_DATA_SCHEMAS, ApplicationValueSchema, _str

APPLICATION_RECORD_TYPE = 'application'
APPLICATION_SECTION_RECORD_TYPE = 'applicationSection'
APPLICATION_TRANSITION_RECORD_TYPE = 'applicationTransition'
APPLICATION_REQUEST_RECORD_TYPE = 'applicationRequest'


def _int() -> Integer:
    return Integer(required=False, allow_none=True)


def _bool() -> Boolean:
    return Boolean(required=False, allow_none=True)


def _enum(enum_cls) -> String:
    return _str(validate=OneOf([member.value for member in enum_cls]))


def _strings() -> List:
    return List(String(required=False, allow_none=True), required=False, allow_none=True)


class PendingActionSchema(ApplicationValueSchema):
    requestId = _str()
    action = _enum(WorkflowAction)
    actorSub = _str()
    expectedStateName = _enum(StateName)
    expectedVersion = _int()
    attempts = _int()
    createdAt = _str()


class ReopenLockSchema(ApplicationValueSchema):
    requestId = _str()
    oldGeneration = _int()
    oldExecutionArn = _str()


class ApplicationTableRecordSchema(BaseRecordSchema):
    """Shared key handling for application-table items. Business fields stay optional."""

    pk = String(required=False, allow_none=False)
    sk = String(required=False, allow_none=False)
    type = String(required=False, allow_none=False)
    dateOfUpdate = AwareDateTime(required=False, allow_none=False)
    compact = _str()
    applicationId = _str()

    @post_load
    def drop_base_gen_fields(self, in_data, **_kwargs):
        in_data.pop('pk', None)
        in_data.pop('sk', None)
        return in_data

    def _partition_key(self, in_data) -> str | None:
        compact = in_data.get('compact')
        application_id = in_data.get('applicationId')
        if compact and application_id:
            return f'{compact}#APPLICATION#{application_id}'
        return None


@BaseRecordSchema.register_schema(APPLICATION_RECORD_TYPE)
class ApplicationRecordSchema(ApplicationTableRecordSchema):
    """Application-level record stored at sk = APPLICATION."""

    _record_type = APPLICATION_RECORD_TYPE

    providerId = _str()
    types = List(_enum(ApplicationType), required=False, allow_none=True)
    isRenewal = _bool()
    status = _enum(ApplicationStatus)
    stateName = _enum(StateName)
    executionArn = _str()
    generation = _int()
    workflowExpiresAt = _str()
    scheduleName = _str()
    taskToken = _str()
    taskTokenHash = _str()
    version = _int()
    pendingAction = Nested(PendingActionSchema, required=False, allow_none=True)
    lastEnteredKey = _str()
    reopenLock = Nested(ReopenLockSchema, required=False, allow_none=True)
    lastExecutionError = _str()
    deactivationReason = _str()
    created = _str()
    submitted = _str()
    completed = _str()
    attestations = _strings()
    paymentCompensated = List(_enum(ApplicationType), required=False, allow_none=True)
    reviews = List(Nested(ApplicationReviewSchema), required=False, allow_none=True)
    firstReviewerSub = _str()
    secondReviewerSub = _str()
    finalReviewerSub = _str()
    firstReviewerAssignmentId = _str()
    secondReviewerAssignmentId = _str()
    finalReviewerAssignmentId = _str()
    firstReviewerFirstName = _str()
    firstReviewerLastName = _str()
    secondReviewerFirstName = _str()
    secondReviewerLastName = _str()
    finalReviewerFirstName = _str()
    finalReviewerLastName = _str()
    statusGSIPK = _str()
    statusGSISK = _str()
    actorGSIPK = _str()
    actorGSISK = _str()
    applicantGSIPK = _str()
    applicantGSISK = _str()

    @pre_dump
    def generate_pk_sk(self, in_data, **kwargs):
        partition_key = self._partition_key(in_data)
        if partition_key:
            in_data['pk'] = partition_key
            in_data['sk'] = 'APPLICATION'
        compact = in_data.get('compact')
        application_id = in_data.get('applicationId')
        status = in_data.get('status')
        if compact and status:
            in_data['statusGSIPK'] = f'{compact}#STATUS#{status}'
        provider_id = in_data.get('providerId')
        if compact and provider_id:
            in_data['applicantGSIPK'] = f'{compact}#PROVIDER#{provider_id}'
            if application_id:
                in_data['applicantGSISK'] = str(application_id)
        return in_data

    @pre_dump
    def populate_date_of_update(self, in_data, **_kwargs):
        in_data['dateOfUpdate'] = config.current_standard_datetime
        compact = in_data.get('compact')
        application_id = in_data.get('applicationId')
        if compact and in_data.get('status') and application_id:
            in_data['statusGSISK'] = f'{in_data["dateOfUpdate"].isoformat()}#{application_id}'
        return in_data


@BaseRecordSchema.register_schema(APPLICATION_SECTION_RECORD_TYPE)
class ApplicationSectionRecordSchema(ApplicationTableRecordSchema):
    """One section item, stored at sk = SECTION#{sectionName}."""

    _record_type = APPLICATION_SECTION_RECORD_TYPE

    sectionName = _enum(SectionName)
    data = Dict(required=False, allow_none=True)
    reviews = List(Nested(ApplicationSectionReviewSchema), required=False, allow_none=True)
    updated = _str()

    def _validated_section_data(self, in_data, *, load: bool):
        section_name = in_data.get('sectionName')
        section_data = in_data.get('data')
        if section_data is None:
            return section_data
        if hasattr(section_name, 'value'):
            section_name = section_name.value
        schema_cls = SECTION_DATA_SCHEMAS.get(section_name)
        if schema_cls is None:
            raise ValidationError({'sectionName': ['Unknown section.']})
        schema = schema_cls()
        return schema.load(section_data) if load else schema.dump(section_data)

    @pre_dump
    def generate_pk_sk(self, in_data, **kwargs):
        if 'data' in in_data:
            in_data['data'] = self._validated_section_data(in_data, load=False)
        partition_key = self._partition_key(in_data)
        section_name = in_data.get('sectionName')
        if hasattr(section_name, 'value'):
            section_name = section_name.value
        if partition_key and section_name:
            in_data['pk'] = partition_key
            in_data['sk'] = f'SECTION#{section_name}'
        return in_data

    @post_load
    def load_section_data(self, in_data, **kwargs):
        if 'data' in in_data:
            in_data['data'] = self._validated_section_data(in_data, load=True)
        return in_data


@BaseRecordSchema.register_schema(APPLICATION_TRANSITION_RECORD_TYPE)
class ApplicationTransitionRecordSchema(ApplicationTableRecordSchema):
    """Audit item stored at sk = TRANSITION#{enteredTime}#{stateName}."""

    _record_type = APPLICATION_TRANSITION_RECORD_TYPE

    fromState = _enum(StateName)
    toState = _enum(StateName)
    action = _enum(WorkflowAction)
    actorSub = _str()
    requestId = _str()
    enteredTime = _str()
    executionArn = _str()

    @pre_dump
    def generate_pk_sk(self, in_data, **kwargs):
        partition_key = self._partition_key(in_data)
        entered_time = in_data.get('enteredTime')
        state_name = in_data.get('toState')
        if partition_key and entered_time and state_name:
            in_data['pk'] = partition_key
            in_data['sk'] = f'TRANSITION#{entered_time}#{state_name}'
        return in_data


@BaseRecordSchema.register_schema(APPLICATION_REQUEST_RECORD_TYPE)
class ApplicationRequestRecordSchema(ApplicationTableRecordSchema):
    """Idempotency item stored at sk = REQUEST#{requestId}."""

    _record_type = APPLICATION_REQUEST_RECORD_TYPE

    requestId = _str()
    action = _enum(WorkflowAction)
    result = Raw(required=False, allow_none=True)
    createdAt = _str()
    ttl = _int()

    @pre_dump
    def generate_pk_sk(self, in_data, **kwargs):
        partition_key = self._partition_key(in_data)
        request_id = in_data.get('requestId')
        if partition_key and request_id:
            in_data['pk'] = partition_key
            in_data['sk'] = f'REQUEST#{request_id}'
        return in_data


class ApplicationData(CCDataClass):
    """Application-level record."""

    _record_schema = ApplicationRecordSchema()

    @property
    def applicationId(self) -> str | None:
        return self._data.get('applicationId')

    @property
    def compact(self) -> str | None:
        return self._data.get('compact')

    @property
    def providerId(self) -> str | None:
        return self._data.get('providerId')

    @property
    def status(self) -> str | None:
        return self._data.get('status')

    @property
    def stateName(self) -> str | None:
        return self._data.get('stateName')

    @property
    def version(self) -> int | None:
        return self._data.get('version')


class ApplicationSectionData(CCDataClass):
    """One section item."""

    _record_schema = ApplicationSectionRecordSchema()

    @property
    def sectionName(self) -> str | None:
        return self._data.get('sectionName')


class ApplicationTransitionData(CCDataClass):
    """One workflow audit item."""

    _record_schema = ApplicationTransitionRecordSchema()


class ApplicationRequestData(CCDataClass):
    """One idempotency item."""

    _record_schema = ApplicationRequestRecordSchema()
