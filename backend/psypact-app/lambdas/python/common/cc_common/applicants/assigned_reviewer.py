"""Current reviewer assignment stored as one map per role."""

from collections.abc import Mapping

ASSIGNED_REVIEWER_METADATA_FIELDS = {
    'first-reviewer': 'assignedFirstReviewerMetadata',
    'second-reviewer': 'assignedSecondReviewerMetadata',
    'final-reviewer': 'assignedFinalReviewerMetadata',
}


def assigned_reviewer_metadata(application: Mapping | None, reviewer_type: str) -> dict:
    """Return the current assignment map for a reviewer role, or an empty map."""
    field_name = ASSIGNED_REVIEWER_METADATA_FIELDS.get(reviewer_type)
    if not field_name or not application:
        return {}
    value = application.get(field_name) or {}
    return value if isinstance(value, dict) else {}
