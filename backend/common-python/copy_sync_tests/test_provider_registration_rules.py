"""Checks for the provider registration WHOLE_FILE_COMPARE_EXCLUSIONS entry only.

provider_registration.py is not a whole-file copy of Compact Connect registration.py.
PSYPACT calls the duplicate-signup helpers and does not run the license-match handler.
A whole-file copy cannot be imported: registration.py imports the Compact Connect
provider schema from schema.provider, and that path in common-python is the Cosmetology
schema. This module checks that the copied function bodies still match the source.
Do not add another mixed-lineage file's checks here.
"""

import ast
import difflib
import unittest

from copy_sync_tests.copied_file_text import REPO_ROOT, function_source, normalize_copied_body

REGISTRATION_RULES = REPO_ROOT / 'backend/common-python/common_lambdas/provider_registration.py'
JCC_REGISTRATION = REPO_ROOT / 'backend/compact-connect/lambdas/python/provider-data-v1/handlers/registration.py'

COPIED_REGISTRATION_FUNCTIONS = frozenset(
    {
        '_rate_limit_exceeded',
        '_should_allow_reregistration',
        '_resend_invitation_and_complete',
        '_cleanup_old_registration',
        '_send_registration_attempt_notification_and_complete',
    }
)


def _module_functions(source: str) -> dict[str, ast.AST]:
    tree = ast.parse(source)
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


class TestProviderRegistrationRules(unittest.TestCase):
    def test_copied_registration_functions_match_compact_connect(self):
        """Every copied registration helper body equals the Compact Connect function."""
        dest_text = REGISTRATION_RULES.read_text(encoding='utf-8')
        source_text = JCC_REGISTRATION.read_text(encoding='utf-8')
        dest_functions = _module_functions(dest_text)
        source_functions = _module_functions(source_text)
        self.assertEqual(COPIED_REGISTRATION_FUNCTIONS, set(dest_functions))

        mismatches: list[str] = []
        for name in sorted(COPIED_REGISTRATION_FUNCTIONS):
            dest_source = normalize_copied_body(function_source(dest_text, dest_functions[name])).strip()
            source_source = function_source(source_text, source_functions[name]).strip()
            if dest_source != source_source:
                mismatches.append(
                    f'{name}\n'
                    + ''.join(
                        difflib.unified_diff(
                            source_source.splitlines(keepends=True),
                            dest_source.splitlines(keepends=True),
                            fromfile=f'registration.{name}',
                            tofile=f'provider_registration.{name}',
                        )
                    )
                )
        self.assertEqual(
            [],
            [mismatch.split('\n', 1)[0] for mismatch in mismatches],
            'Registration helper bodies drifted from Compact Connect registration.py. '
            'Re-copy the function text. Do not edit a copied body by hand.\n\n' + '\n\n'.join(mismatches),
        )
