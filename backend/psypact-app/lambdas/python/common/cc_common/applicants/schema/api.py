# ruff: noqa: N801, N815  invalid-name
"""HTTP request and response schemas.

Stored fields live in the Dynamo schemas. This module describes what a caller
sends and what the UI receives. A response may add a calculated field or replace
a stored ``s3Key`` with a presigned ``downloadUri``.
"""

from common_lambdas.data_model.schema.base_record import ForgivingSchema
from common_lambdas.data_model.schema.common import CCRequestSchema
from marshmallow import EXCLUDE, RAISE, pre_dump
from marshmallow.fields import Boolean, Integer, List, Nested, String
from marshmallow.validate import Length, OneOf

from cc_common.applicants.application_state import (
    ApplicantSectionStatus,
    ApplicationStatus,
    ApplicationType,
    ReviewComparisonStatus,
    ReviewerType,
    ReviewSectionStatus,
    SectionName,
    StateName,
    WorkflowAction,
)
from cc_common.applicants.schema.calculated import calculate_applicant_status, calculate_review_comparison
from cc_common.applicants.schema.reviews import (
    NOTE_MAX_LENGTH,
    ApplicationReviewSchema,
    ApplicationSectionReviewSchema,
)
from cc_common.applicants.schema.sections import (
    AcknowledgementsSchema,
    ApplicationValueSchema,
    ConductHistorySchema,
    EducationSchema,
    HomeStateApplicationTypeSchema,
    HomeStateSchema,
    LicenseHistorySchema,
    PersonalInformationSchema,
    _str,
    section_data_schema,
)

_ASSIGNMENT_ID_FIELDS = {
    ReviewerType.FIRST_REVIEWER.value: 'firstReviewerAssignmentId',
    ReviewerType.SECOND_REVIEWER.value: 'secondReviewerAssignmentId',
    ReviewerType.FINAL_REVIEWER.value: 'finalReviewerAssignmentId',
}


def _enum(enum_cls, **kwargs) -> String:
    return _str(validate=OneOf([member.value for member in enum_cls]), **kwargs)


def _note() -> String:
    return _str(validate=Length(max=NOTE_MAX_LENGTH))


def _strings() -> List:
    return List(String(required=False, allow_none=True), required=False, allow_none=True)


class StrictRequestSchema(CCRequestSchema):
    """Incoming request. Unknown fields are rejected."""

    class Meta:
        unknown = RAISE


class SectionReviewRequestSchema(StrictRequestSchema):
    sectionStatus = _enum(ReviewSectionStatus)
    notesForApplicant = _note()
    notesForReviewers = _note()


class TransitionRequestSchema(StrictRequestSchema):
    action = _enum(WorkflowAction, required=True, allow_none=False)
    notesForApplicant = _note()
    notesForReviewers = _note()
    requestId = _str(required=True, allow_none=False)


class SetApplicationStatusRequestSchema(StrictRequestSchema):
    targetState = _enum(StateName, required=True, allow_none=False)
    reason = _note()
    requestId = _str(required=True, allow_none=False)


class AssignReviewersRequestSchema(StrictRequestSchema):
    firstReviewerSub = _str()
    secondReviewerSub = _str()
    finalReviewerSub = _str()


class ReopenApplicationRequestSchema(StrictRequestSchema):
    requestId = _str()
    reason = _note()


class CreateApplicationRequestSchema(StrictRequestSchema):
    """Practitioner create body. ``types`` is one or both of ``apit`` and ``tap``."""

    types = List(_enum(ApplicationType), required=True, allow_none=False, validate=Length(min=1))
    isRenewal = Boolean(required=True, allow_none=False)


class ApplicantSubmissionRequestSchema(StrictRequestSchema):
    """Submit or resubmit. The handler generates ``requestId`` when the caller omits it."""

    requestId = _str()


class ResponseDocumentSchema(ApplicationValueSchema):
    """File metadata returned to the UI. ``downloadUri`` is generated at read time."""

    filename = _str()
    sizeBytes = Integer(required=False, allow_none=True)
    downloadUri = _str()


class EducationResponseSchema(EducationSchema):
    transcripts = List(Nested(ResponseDocumentSchema), required=False, allow_none=True)


class ConductHistoryResponseSchema(ConductHistorySchema):
    documents = List(Nested(ResponseDocumentSchema), required=False, allow_none=True)


class HomeStateApplicationTypeResponseSchema(HomeStateApplicationTypeSchema):
    militaryDocuments = List(Nested(ResponseDocumentSchema), required=False, allow_none=True)


class HomeStateResponseSchema(HomeStateSchema):
    applicationTypes = List(Nested(HomeStateApplicationTypeResponseSchema), required=False, allow_none=True)


class _CalculatedSectionFields(ForgivingSchema):
    calculatedSectionStatusForApplicant = _enum(ApplicantSectionStatus)
    calculatedSectionStatusForReviewComparison = _enum(ReviewComparisonStatus)
    reviews = List(Nested(ApplicationSectionReviewSchema), required=False, allow_none=True)


class PersonalInformationResponseSchema(PersonalInformationSchema, _CalculatedSectionFields):
    pass


class LicenseHistoryResponseSchema(LicenseHistorySchema, _CalculatedSectionFields):
    pass


class EducationSectionResponseSchema(EducationResponseSchema, _CalculatedSectionFields):
    pass


class ConductHistorySectionResponseSchema(ConductHistoryResponseSchema, _CalculatedSectionFields):
    pass


class HomeStateSectionResponseSchema(HomeStateResponseSchema, _CalculatedSectionFields):
    pass


class AcknowledgementsResponseSchema(AcknowledgementsSchema, _CalculatedSectionFields):
    pass


_OMITTED_PROVIDER_REVIEW_FIELDS = (
    'assignmentId',
    'reviewerType',
    'reviewer',
    'assignedDate',
    'notesForReviewers',
)

_STAFF_RESPONSE_FIELDS = (
    'stateName',
    'providerId',
    'firstReviewerSub',
    'secondReviewerSub',
    'finalReviewerSub',
    'firstReviewerFirstName',
    'firstReviewerLastName',
    'secondReviewerFirstName',
    'secondReviewerLastName',
    'finalReviewerFirstName',
    'finalReviewerLastName',
)


class ProviderApplicationReviewSchema(ApplicationReviewSchema):
    """Provider application review. Reviewer identity is omitted."""

    class Meta:
        unknown = EXCLUDE
        exclude = (*_OMITTED_PROVIDER_REVIEW_FIELDS, 'reviewerSelectedApplicationStatus')


class ProviderApplicationSectionReviewSchema(ApplicationSectionReviewSchema):
    """Provider section review. Reviewer identity is omitted."""

    class Meta:
        unknown = EXCLUDE
        exclude = (*_OMITTED_PROVIDER_REVIEW_FIELDS, 'reviewerSelectedApplicationSectionStatus')


def _provider_section(schema_cls):
    """Section response whose reviews use the provider review schema."""

    class ProviderSectionSchema(schema_cls):
        reviews = List(Nested(ProviderApplicationSectionReviewSchema), required=False, allow_none=True)

    ProviderSectionSchema.__name__ = f'Provider{schema_cls.__name__}'
    return ProviderSectionSchema


ProviderPersonalInformationResponseSchema = _provider_section(PersonalInformationResponseSchema)
ProviderLicenseHistoryResponseSchema = _provider_section(LicenseHistoryResponseSchema)
ProviderEducationSectionResponseSchema = _provider_section(EducationSectionResponseSchema)
ProviderConductHistorySectionResponseSchema = _provider_section(ConductHistorySectionResponseSchema)
ProviderHomeStateSectionResponseSchema = _provider_section(HomeStateSectionResponseSchema)
ProviderAcknowledgementsResponseSchema = _provider_section(AcknowledgementsResponseSchema)


def _completed_reviews(reviews):
    """Keep reviews that have been completed. An assignment shell has no completion date."""
    if not reviews:
        return reviews
    return [review for review in reviews if review.get('reviewCompletionDate')]


class StaffApplicationResponseSchema(ForgivingSchema):
    """Full application returned to compact admins, including reviewer identity."""

    id = _str()
    created = _str()
    submitted = _str()
    completed = _str()
    types = List(_enum(ApplicationType), required=False, allow_none=True)
    isRenewal = Boolean(required=False, allow_none=True)
    status = _enum(ApplicationStatus)
    reviews = List(Nested(ApplicationReviewSchema), required=False, allow_none=True)
    attestations = _strings()
    paymentCompensated = List(_enum(ApplicationType), required=False, allow_none=True)
    personalInformation = Nested(PersonalInformationResponseSchema, required=False, allow_none=True)
    licenseHistory = Nested(LicenseHistoryResponseSchema, required=False, allow_none=True)
    education = Nested(EducationSectionResponseSchema, required=False, allow_none=True)
    conductHistory = Nested(ConductHistorySectionResponseSchema, required=False, allow_none=True)
    homeState = Nested(HomeStateSectionResponseSchema, required=False, allow_none=True)
    acknowledgements = Nested(AcknowledgementsResponseSchema, required=False, allow_none=True)
    stateName = _enum(StateName)
    providerId = _str()
    firstReviewerSub = _str()
    secondReviewerSub = _str()
    finalReviewerSub = _str()
    firstReviewerFirstName = _str()
    firstReviewerLastName = _str()
    secondReviewerFirstName = _str()
    secondReviewerLastName = _str()
    finalReviewerFirstName = _str()
    finalReviewerLastName = _str()


class ApplicationResponseSchema(StaffApplicationResponseSchema):
    """Provider application. Staff-only fields and incomplete reviews are omitted."""

    class Meta:
        unknown = EXCLUDE
        exclude = _STAFF_RESPONSE_FIELDS

    reviews = List(Nested(ProviderApplicationReviewSchema), required=False, allow_none=True)
    personalInformation = Nested(ProviderPersonalInformationResponseSchema, required=False, allow_none=True)
    licenseHistory = Nested(ProviderLicenseHistoryResponseSchema, required=False, allow_none=True)
    education = Nested(ProviderEducationSectionResponseSchema, required=False, allow_none=True)
    conductHistory = Nested(ProviderConductHistorySectionResponseSchema, required=False, allow_none=True)
    homeState = Nested(ProviderHomeStateSectionResponseSchema, required=False, allow_none=True)
    acknowledgements = Nested(ProviderAcknowledgementsResponseSchema, required=False, allow_none=True)

    @pre_dump
    def omit_incomplete_reviews(self, data, **kwargs):
        del kwargs
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if 'reviews' in data:
            data['reviews'] = _completed_reviews(data.get('reviews'))
        for section_name in SectionName:
            section = data.get(section_name.value)
            if isinstance(section, dict) and 'reviews' in section:
                section = dict(section)
                section['reviews'] = _completed_reviews(section.get('reviews'))
                data[section_name.value] = section
        return data


def section_patch_schema(section_name: str):
    """Validate a section PATCH body as the stored section document."""
    return section_data_schema(section_name)


def _enum_value(value):
    return value.value if hasattr(value, 'value') else value


def _current_reviews(application_item: dict, reviews: list) -> list:
    current = []
    for review in reviews:
        reviewer_type = _enum_value(review.get('reviewerType'))
        assignment_field = _ASSIGNMENT_ID_FIELDS.get(reviewer_type)
        assignment_id = application_item.get(assignment_field) if assignment_field else None
        if assignment_id and review.get('assignmentId') == assignment_id:
            current.append(review)
    return current


def _review_for(reviews: list, reviewer_type: str) -> dict | None:
    for review in reviews:
        if _enum_value(review.get('reviewerType')) == reviewer_type:
            return review
    return None


def assemble_application_response(application_item: dict, section_items: list[dict], *, response_schema=None) -> dict:
    """Build the UI application from stored items. This does not call AWS."""
    stored_sections = {}
    for item in section_items or []:
        section_name = _enum_value(item.get('sectionName'))
        if section_name:
            stored_sections[section_name] = item

    response = {}
    application_id = application_item.get('applicationId', application_item.get('id'))
    if application_id is not None:
        response['id'] = application_id
    for field_name in (
        'created',
        'submitted',
        'completed',
        'types',
        'isRenewal',
        'status',
        'reviews',
        'attestations',
        'paymentCompensated',
    ):
        if application_item.get(field_name) is not None:
            response[field_name] = application_item[field_name]
    for field_name in _STAFF_RESPONSE_FIELDS:
        if application_item.get(field_name) is not None:
            response[field_name] = application_item[field_name]

    for section_name in SectionName:
        item = stored_sections.get(section_name.value, {})
        data = dict(item.get('data') or {})
        reviews = list(item.get('reviews') or [])
        current = _current_reviews(application_item, reviews)
        data['reviews'] = reviews
        data['calculatedSectionStatusForApplicant'] = calculate_applicant_status(
            item.get('data'),
            application_item.get('status'),
            current,
            application_item.get('isRenewal'),
        )
        data['calculatedSectionStatusForReviewComparison'] = calculate_review_comparison(
            _review_for(current, ReviewerType.FIRST_REVIEWER.value),
            _review_for(current, ReviewerType.SECOND_REVIEWER.value),
        )
        response[section_name.value] = data

    schema = ApplicationResponseSchema if response_schema is None else response_schema
    return schema().dump(response)
