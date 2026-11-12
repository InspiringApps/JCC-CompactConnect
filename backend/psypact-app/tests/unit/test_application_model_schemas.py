import importlib.util
import json
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHECKED_IN = _APP_ROOT / 'stacks/api_stack/v1_api/generated_application_schemas.json'


def _build_application_model_schemas():
    # Load the builder by file path so this test does not import the CDK stacks package.
    spec = importlib.util.spec_from_file_location(
        'build_application_schemas',
        _APP_ROOT / 'stacks/api_stack/v1_api/build_application_schemas.py',
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_application_model_schemas()


class TestApplicationModelSchemas(unittest.TestCase):
    def test_checked_in_schemas_match_the_marshmallow_models(self):
        self.assertEqual(_build_application_model_schemas(), json.loads(_CHECKED_IN.read_text()))
