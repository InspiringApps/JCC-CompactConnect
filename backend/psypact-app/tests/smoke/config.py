import ast
import json
import os
from pathlib import Path

from _common_smoke import COMMON_PYTHON, add_common_python_to_path

add_common_python_to_path()

# The copied module calls load_smoke_test_env() at import and looks for
# smoke_tests_env.json beside itself. Skip those trailing statements so this
# directory's env file is the one that loads, then subclass the copied config.
_copied_config = COMMON_PYTHON / 'common_smoke_test' / 'compact_connect_config.py'
_copied_text = _copied_config.read_text(encoding='utf-8')
if _copied_text.startswith('# Copied from'):
    _copied_text = _copied_text.split('\n', 1)[1].lstrip('\n')
_module = ast.parse(_copied_text)
_kept_body = []
for _node in _module.body:
    if isinstance(_node, ast.Expr) and isinstance(_node.value, ast.Call) and isinstance(_node.value.func, ast.Name):
        if _node.value.func.id == 'load_smoke_test_env':
            continue
    if isinstance(_node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == 'config' for target in _node.targets
    ):
        continue
    _kept_body.append(_node)
_module.body = _kept_body
ast.fix_missing_locations(_module)
_config_namespace: dict = {'__file__': str(Path(__file__).resolve()), '__name__': 'compact_connect_config_base'}
exec(compile(_module, str(_copied_config), 'exec'), _config_namespace)  # noqa: S102

_CompactConnectConfig = _config_namespace['_Config']
logger = _config_namespace['logger']


class _Config(_CompactConnectConfig):
    @property
    def test_provider_id(self):
        """Provider id of a practitioner who already has license records in the test environment."""
        return os.environ['CC_TEST_PROVIDER_ID']


def load_smoke_test_env():
    with open(os.path.join(os.path.dirname(__file__), 'smoke_tests_env.json')) as env_file:
        env_vars = json.load(env_file)
        os.environ.update(env_vars)


load_smoke_test_env()
config = _Config()
