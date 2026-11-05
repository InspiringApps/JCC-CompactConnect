# ruff: noqa: N801, N815  invalid-name
"""Application-level and section-level review objects stored on their parent items."""

from marshmallow.fields import Nested, String
from marshmallow.validate import Length, OneOf

from cc_common.application_state import ApplicationStatus, ReviewerType, ReviewSectionStatus
from cc_common.schema.application.sections import ApplicationValueSchema, _str

NOTE_MAX_LENGTH = 1000


def _note() -> String:
    return _str(validate=Length(max=NOTE_MAX_LENGTH))


class ReviewerSchema(ApplicationValueSchema):
    """Reviewer identity. ``id`` is the Cognito sub."""

    id = _str()
    firstName = _str()
    lastName = _str()


class ReviewSchema(ApplicationValueSchema):
    assignmentId = _str()
    reviewerType = _str(validate=OneOf([reviewer_type.value for reviewer_type in ReviewerType]))
    reviewer = Nested(ReviewerSchema, required=False, allow_none=True)
    assignedDate = _str()
    reviewCompletionDate = _str()
    notesForApplicant = _note()
    notesForReviewers = _note()


class ApplicationReviewSchema(ReviewSchema):
    reviewerSelectedApplicationStatus = _str(validate=OneOf([status.value for status in ApplicationStatus]))


class ApplicationSectionReviewSchema(ReviewSchema):
    reviewerSelectedApplicationSectionStatus = _str(validate=OneOf([status.value for status in ReviewSectionStatus]))
