"""Regenerate the checked-in application API schemas from marshmallow.

CDK synth must not import this module. The pipeline image does not install marshmallow.
"""

import os
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
for _path in (_APP_ROOT.parent / 'common-python', _APP_ROOT / 'lambdas' / 'python' / 'common'):
    _text = str(_path)
    if _path.is_dir() and _text not in sys.path:
        sys.path.insert(0, _text)

os.environ.setdefault('COMPACTS', '["aslp", "octp", "coun", "psypact"]')
os.environ.setdefault('JURISDICTIONS', '["oh"]')
os.environ.setdefault(
    'LICENSE_TYPES',
    '{"psypact": [{"name": "psychologist", "abbreviation": "psy"}]}',
)

from cc_common.applicants.schema.api import (  # noqa: E402
    AcknowledgementsResponseSchema,
    ApplicantSubmissionRequestSchema,
    ApplicationAcceptedResponseSchema,
    ApplicationResponseSchema,
    AssignReviewersRequestSchema,
    ConductHistorySectionResponseSchema,
    CreateApplicationRequestSchema,
    EducationSectionResponseSchema,
    HomeStateSectionResponseSchema,
    LicenseHistoryResponseSchema,
    PersonalInformationResponseSchema,
    ProviderAcknowledgementsResponseSchema,
    ProviderConductHistorySectionResponseSchema,
    ProviderEducationSectionResponseSchema,
    ProviderHomeStateSectionResponseSchema,
    ProviderLicenseHistoryResponseSchema,
    ProviderPersonalInformationResponseSchema,
    ReopenApplicationRequestSchema,
    SectionReviewRequestSchema,
    SetApplicationStatusRequestSchema,
    StaffApplicationListItemSchema,
    StaffApplicationResponseSchema,
    TransitionRequestSchema,
)
from cc_common.applicants.schema.json_schema import (  # noqa: E402
    marshmallow_json_schema,
    merged_section_response_schema,
)

_PATCH_SECTION_DESCRIPTION = (
    'Stored section document for the {section} path parameter. '
    'The handler validates the body with the section schema for that section.'
)

_SECTION_MODELS = (
    ('PersonalInformation', PersonalInformationResponseSchema, ProviderPersonalInformationResponseSchema),
    ('LicenseHistory', LicenseHistoryResponseSchema, ProviderLicenseHistoryResponseSchema),
    ('Education', EducationSectionResponseSchema, ProviderEducationSectionResponseSchema),
    ('ConductHistory', ConductHistorySectionResponseSchema, ProviderConductHistorySectionResponseSchema),
    ('HomeState', HomeStateSectionResponseSchema, ProviderHomeStateSectionResponseSchema),
    ('Acknowledgements', AcknowledgementsResponseSchema, ProviderAcknowledgementsResponseSchema),
)


def build_application_model_schemas() -> dict:
    """Return the schema dicts that ``generated_application_schemas.json`` must contain."""
    return {
        'CREATE_APPLICATION': marshmallow_json_schema(CreateApplicationRequestSchema),
        'PATCH_SECTION': {'type': 'object', 'description': _PATCH_SECTION_DESCRIPTION},
        'SUBMISSION': marshmallow_json_schema(ApplicantSubmissionRequestSchema),
        'ASSIGN_REVIEWERS': marshmallow_json_schema(AssignReviewersRequestSchema),
        'SECTION_REVIEW': marshmallow_json_schema(SectionReviewRequestSchema),
        'TRANSITION': marshmallow_json_schema(TransitionRequestSchema),
        'SET_STATUS': marshmallow_json_schema(SetApplicationStatusRequestSchema),
        'REOPEN': marshmallow_json_schema(ReopenApplicationRequestSchema),
        'PROVIDER_APPLICATION': marshmallow_json_schema(ApplicationResponseSchema),
        'STAFF_APPLICATION': marshmallow_json_schema(StaffApplicationResponseSchema),
        'ACCEPTED': marshmallow_json_schema(ApplicationAcceptedResponseSchema),
        'STAFF_LIST_ITEM': marshmallow_json_schema(StaffApplicationListItemSchema),
        'PROVIDER_SECTION': merged_section_response_schema(
            ProviderPersonalInformationResponseSchema,
            ProviderLicenseHistoryResponseSchema,
            ProviderEducationSectionResponseSchema,
            ProviderConductHistorySectionResponseSchema,
            ProviderHomeStateSectionResponseSchema,
            ProviderAcknowledgementsResponseSchema,
        ),
        'STAFF_SECTION': merged_section_response_schema(
            PersonalInformationResponseSchema,
            LicenseHistoryResponseSchema,
            EducationSectionResponseSchema,
            ConductHistorySectionResponseSchema,
            HomeStateSectionResponseSchema,
            AcknowledgementsResponseSchema,
        ),
        'SECTION_MODEL_SCHEMAS': {
            f'{prefix}{name}': marshmallow_json_schema(schema_cls)
            for name, staff_schema, provider_schema in _SECTION_MODELS
            for prefix, schema_cls in (('Staff', staff_schema), ('', provider_schema))
        },
    }
