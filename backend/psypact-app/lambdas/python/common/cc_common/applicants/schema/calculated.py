"""Provisional section status calculations.

CONFIRM_DETAILS is unused until renewal-specific required fields exist.
``is_renewal`` is accepted so callers can pass it now; it does not change the result.
"""

from cc_common.applicants.application_state import (
    ApplicantSectionStatus,
    ApplicationStatus,
    ReviewComparisonStatus,
    ReviewSectionStatus,
)

_DECIDED_REVIEW_STATUSES = frozenset({ReviewSectionStatus.APPROVED.value, ReviewSectionStatus.REJECTED.value})


def _value(status) -> str | None:
    if status is None:
        return None
    return status.value if hasattr(status, 'value') else str(status)


def _is_populated(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_is_populated(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_is_populated(item) for item in value)
    return True


def _section_review_status(review: dict | None) -> str | None:
    if not review:
        return None
    return _value(review.get('reviewerSelectedApplicationSectionStatus'))


def calculate_applicant_status(section_data, application_status, current_section_reviews, is_renewal) -> str:
    """Return the applicant-facing status for one section.

    NEEDS_ATTENTION wins when the application is awaiting the applicant and a
    current-assignment review of this section is rejected. Otherwise an empty
    section is INCOMPLETE and any populated field makes it COMPLETE.
    """
    _ = is_renewal
    status = _value(application_status)
    reviews = current_section_reviews or []
    rejected = ReviewSectionStatus.REJECTED.value
    if status == ApplicationStatus.AWAITING_APPLICANT.value and any(
        _section_review_status(review) == rejected for review in reviews
    ):
        return ApplicantSectionStatus.NEEDS_ATTENTION.value
    if not _is_populated(section_data):
        return ApplicantSectionStatus.INCOMPLETE.value
    return ApplicantSectionStatus.COMPLETE.value


def calculate_review_comparison(first_review, second_review) -> str | None:
    """Compare the current first and second reviewer decisions for one section."""
    first = _section_review_status(first_review)
    second = _section_review_status(second_review)
    if first not in _DECIDED_REVIEW_STATUSES or second not in _DECIDED_REVIEW_STATUSES:
        return None
    if first == ReviewSectionStatus.APPROVED.value and second == ReviewSectionStatus.APPROVED.value:
        return ReviewComparisonStatus.BOTH_APPROVE.value
    if first != second:
        return ReviewComparisonStatus.REVIEWERS_DIFFER.value
    return None
