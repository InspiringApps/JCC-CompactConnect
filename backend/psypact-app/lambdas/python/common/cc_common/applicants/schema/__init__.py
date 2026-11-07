"""Marshmallow schemas for the PSYPACT practitioner application."""

from cc_common.applicants.schema.api import (
    ApplicantSubmissionRequestSchema,
    ApplicationResponseSchema,
    AssignReviewersRequestSchema,
    CreateApplicationRequestSchema,
    ReopenApplicationRequestSchema,
    SectionReviewRequestSchema,
    SetApplicationStatusRequestSchema,
    TransitionRequestSchema,
    assemble_application_response,
    section_patch_schema,
)
from cc_common.applicants.schema.calculated import (
    calculate_applicant_status,
    calculate_review_comparison,
)
from cc_common.applicants.schema.records import (
    APPLICATION_RECORD_TYPE,
    APPLICATION_REQUEST_RECORD_TYPE,
    APPLICATION_SECTION_RECORD_TYPE,
    APPLICATION_TRANSITION_RECORD_TYPE,
    ApplicationData,
    ApplicationRecordSchema,
    ApplicationRequestData,
    ApplicationRequestRecordSchema,
    ApplicationSectionData,
    ApplicationSectionRecordSchema,
    ApplicationTransitionData,
    ApplicationTransitionRecordSchema,
)
from cc_common.applicants.schema.reviews import (
    ApplicationReviewSchema,
    ApplicationSectionReviewSchema,
)
from cc_common.applicants.schema.sections import SECTION_DATA_SCHEMAS, section_data_schema

__all__ = [
    'APPLICATION_RECORD_TYPE',
    'APPLICATION_REQUEST_RECORD_TYPE',
    'APPLICATION_SECTION_RECORD_TYPE',
    'APPLICATION_TRANSITION_RECORD_TYPE',
    'ApplicantSubmissionRequestSchema',
    'ApplicationData',
    'ApplicationRecordSchema',
    'ApplicationRequestData',
    'ApplicationRequestRecordSchema',
    'ApplicationResponseSchema',
    'ApplicationReviewSchema',
    'ApplicationSectionData',
    'ApplicationSectionRecordSchema',
    'ApplicationSectionReviewSchema',
    'ApplicationTransitionData',
    'ApplicationTransitionRecordSchema',
    'AssignReviewersRequestSchema',
    'CreateApplicationRequestSchema',
    'ReopenApplicationRequestSchema',
    'SECTION_DATA_SCHEMAS',
    'SectionReviewRequestSchema',
    'SetApplicationStatusRequestSchema',
    'TransitionRequestSchema',
    'assemble_application_response',
    'calculate_applicant_status',
    'calculate_review_comparison',
    'section_data_schema',
    'section_patch_schema',
]
