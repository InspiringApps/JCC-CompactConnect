"""Application API schemas for API Gateway models.

CDK synth imports this module and builds the dicts from the marshmallow schemas.
The pipeline image installs marshmallow with the CDK requirements.
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
    PatchApplicationRequestSchema,
    PatchApplicationReviewsRequestSchema,
    PersonalInformationResponseSchema,
    ProviderAcknowledgementsResponseSchema,
    ProviderConductHistorySectionResponseSchema,
    ProviderEducationSectionResponseSchema,
    ProviderHomeStateSectionResponseSchema,
    ProviderLicenseHistoryResponseSchema,
    ProviderPersonalInformationResponseSchema,
    ReopenApplicationRequestSchema,
    SetApplicationStatusRequestSchema,
    StaffApplicationListItemSchema,
    StaffApplicationResponseSchema,
    TransitionRequestSchema,
)
from cc_common.applicants.schema.json_schema import marshmallow_json_schema  # noqa: E402

CREATE_APPLICATION = marshmallow_json_schema(CreateApplicationRequestSchema)
PATCH_APPLICATION = marshmallow_json_schema(PatchApplicationRequestSchema)
PATCH_APPLICATION_REVIEWS = marshmallow_json_schema(PatchApplicationReviewsRequestSchema)
SUBMISSION = marshmallow_json_schema(ApplicantSubmissionRequestSchema)
ASSIGN_REVIEWERS = marshmallow_json_schema(AssignReviewersRequestSchema)
TRANSITION = marshmallow_json_schema(TransitionRequestSchema)
SET_STATUS = marshmallow_json_schema(SetApplicationStatusRequestSchema)
REOPEN = marshmallow_json_schema(ReopenApplicationRequestSchema)
PROVIDER_APPLICATION = marshmallow_json_schema(ApplicationResponseSchema)
STAFF_APPLICATION = marshmallow_json_schema(StaffApplicationResponseSchema)
ACCEPTED = marshmallow_json_schema(ApplicationAcceptedResponseSchema)
STAFF_LIST_ITEM = marshmallow_json_schema(StaffApplicationListItemSchema)
_SECTION_MODELS = (
    ('PersonalInformation', PersonalInformationResponseSchema, ProviderPersonalInformationResponseSchema),
    ('LicenseHistory', LicenseHistoryResponseSchema, ProviderLicenseHistoryResponseSchema),
    ('Education', EducationSectionResponseSchema, ProviderEducationSectionResponseSchema),
    ('ConductHistory', ConductHistorySectionResponseSchema, ProviderConductHistorySectionResponseSchema),
    ('HomeState', HomeStateSectionResponseSchema, ProviderHomeStateSectionResponseSchema),
    ('Acknowledgements', AcknowledgementsResponseSchema, ProviderAcknowledgementsResponseSchema),
)
SECTION_MODEL_SCHEMAS = {
    f'{prefix}{name}': marshmallow_json_schema(schema_cls)
    for name, staff_schema, provider_schema in _SECTION_MODELS
    for prefix, schema_cls in (('Staff', staff_schema), ('', provider_schema))
}
