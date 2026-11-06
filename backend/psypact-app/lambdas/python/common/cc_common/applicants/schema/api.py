# ruff: noqa: N801, N815  invalid-name
"""Request and response schemas for the application API."""

from common_lambdas.data_model.schema.base_record import ForgivingSchema
from common_lambdas.data_model.schema.common import CCRequestSchema
from marshmallow import RAISE
from marshmallow.fields import Boolean, List, Nested, String
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
    ConductHistorySchema,
    EducationSchema,
    HomeStateApplicationTypeSchema,
    HomeStateSchema,
    LicenseHistorySchema,
    PersonalInformationSchema,
    ResponseDocumentSchema,
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


class ApplicationResponseSchema(ForgivingSchema):
    """UI application. Workflow internals are not fields, so they are never emitted."""

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


def section_patch_schema(section_name: str):
    """Schema for a section PATCH body. The body is that section's fields."""
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


def assemble_application_response(application_item: dict, section_items: list[dict]) -> dict:
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

    return ApplicationResponseSchema().dump(response)
