"""Application API schemas for API Gateway models.

The dicts are generated from the marshmallow schemas and checked in. CDK synth
loads this file only, so the pipeline image does not need marshmallow.
``build_application_schemas.py`` regenerates the JSON when those schemas change.
"""

import json
from pathlib import Path

_SCHEMAS = json.loads((Path(__file__).with_name('generated_application_schemas.json')).read_text())

CREATE_APPLICATION = _SCHEMAS['CREATE_APPLICATION']
PATCH_SECTION = _SCHEMAS['PATCH_SECTION']
SUBMISSION = _SCHEMAS['SUBMISSION']
ASSIGN_REVIEWERS = _SCHEMAS['ASSIGN_REVIEWERS']
SECTION_REVIEW = _SCHEMAS['SECTION_REVIEW']
TRANSITION = _SCHEMAS['TRANSITION']
SET_STATUS = _SCHEMAS['SET_STATUS']
REOPEN = _SCHEMAS['REOPEN']
PROVIDER_APPLICATION = _SCHEMAS['PROVIDER_APPLICATION']
STAFF_APPLICATION = _SCHEMAS['STAFF_APPLICATION']
ACCEPTED = _SCHEMAS['ACCEPTED']
STAFF_LIST_ITEM = _SCHEMAS['STAFF_LIST_ITEM']
PROVIDER_SECTION = _SCHEMAS['PROVIDER_SECTION']
STAFF_SECTION = _SCHEMAS['STAFF_SECTION']
SECTION_MODEL_SCHEMAS = _SCHEMAS['SECTION_MODEL_SCHEMAS']
