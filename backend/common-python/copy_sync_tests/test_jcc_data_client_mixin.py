"""Checks for the DataClient WHOLE_FILE_COMPARE_EXCLUSIONS entry only.

jcc_data_client_mixin.py is not a whole-file copy of Cosmetology or JCC
DataClient. PSYPACT keeps Cosmetology DataClient as the base class (read-time
privileges) and composes selected JCC DataClient methods onto the same instance.
A full JCC DataClient would restore stored-privilege behavior.

This module covers that one excluded file. Another mixed-lineage exclusion must
get its own test file; do not add those checks here.

Cosmetology methods stay on the base class and must not appear in the mixin
(MRO would hide them). These tests therefore only assert the JCC DataClient
slice: the PSYPACT-required JCC public methods exist, every mixin method body
matches JCC DataClient, and extraction did not drop imports those bodies need.
"""

import ast
import difflib
import unittest

from copy_sync_tests.copied_file_text import COMMON_PYTHON_ROOT, all_copied_files, comparable_method_sources

DATA_CLIENT_MIXIN_DEST = 'common_lambdas/data_model/jcc_data_client_mixin.py'

# JCC DataClient methods that selected PSYPACT handlers call and Cosmetology
# DataClient does not implement. Extraction starts here and pulls in JCC-only
# helpers those methods call.
PSYPACT_REQUIRED_JCC_DATA_CLIENT_METHODS = frozenset(
    {
        'update_provider_home_state_jurisdiction',
        'create_military_affiliation',
        'end_military_affiliation',
        'update_provider_email_verification_data',
        'clear_provider_email_verification_data',
        'complete_provider_email_update',
        'update_provider_account_recovery_data',
        'clear_provider_account_recovery_data',
        'get_privilege_for_transaction_id',
    }
)


def _as_lines(value: str | bytes) -> list[str]:
    if isinstance(value, bytes):
        return [f'{line!r}\n' for line in value.splitlines(keepends=True)]
    return value.splitlines(keepends=True)


def _unified_diff(source: str | bytes, copy: str | bytes, source_path: str, copy_path: str) -> str:
    return ''.join(
        difflib.unified_diff(
            _as_lines(source),
            _as_lines(copy),
            fromfile=source_path,
            tofile=copy_path,
            n=3,
        )
    )


class TestJccDataClientMixin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.copied_files = all_copied_files()

    def _dest_rel(self, copied) -> str:
        return copied.dest.relative_to(COMMON_PYTHON_ROOT).as_posix()

    def test_data_client_mixin_methods_match_jcc_data_client(self):
        """Mixin includes the PSYPACT-required JCC methods, and every mixin method body equals JCC DataClient."""
        mixin = next(copied for copied in self.copied_files if self._dest_rel(copied) == DATA_CLIENT_MIXIN_DEST)
        compared = comparable_method_sources(
            mixin,
            dest_class='JccDataClientMixin',
            source_class='DataClient',
        )
        missing_required = sorted(PSYPACT_REQUIRED_JCC_DATA_CLIENT_METHODS - compared.keys())
        self.assertEqual(
            missing_required,
            [],
            'jcc_data_client_mixin.py is missing JCC DataClient methods PSYPACT handlers call.',
        )
        mismatches: list[str] = []
        for name, (dest_source, source_source) in compared.items():
            if dest_source != source_source:
                mismatches.append(
                    f'{name}\n' + _unified_diff(source_source, dest_source, f'DataClient.{name}', f'mixin.{name}')
                )
        self.assertEqual(
            [],
            [mismatch.split('\n', 1)[0] for mismatch in mismatches],
            'DataClient mixin method bodies drifted from JCC DataClient. Re-extract the method; '
            'do not edit it by hand. Re-extract only if the JCC change is backwards compatible '
            'with existing callers of those methods (treat the mixin like a package minor/patch). '
            'If the JCC change is breaking, keep the current mixin bodies and put the new behavior '
            'in a JCC-only wrapper until every consumer can take it.\n\n' + '\n\n'.join(mismatches),
        )

    def test_data_client_mixin_imports_cover_names_used_in_methods(self):
        """Mixin method bodies still resolve after extraction; truncated imports like the old email mixin fail here."""
        source = (COMMON_PYTHON_ROOT / DATA_CLIENT_MIXIN_DEST).read_text(encoding='utf-8')
        tree = ast.parse(source)
        builtins_ns = __builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__
        available: set[str] = set(builtins_ns)
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    available.add(alias.asname or alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    available.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        available.add(target.id)
            elif isinstance(node, ast.ClassDef):
                available.add(node.name)

        class_def = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'JccDataClientMixin'
        )
        missing: list[str] = []
        for fn in class_def.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            local = {arg.arg for arg in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)}
            if fn.args.vararg:
                local.add(fn.args.vararg.arg)
            if fn.args.kwarg:
                local.add(fn.args.kwarg.arg)
            for child in ast.walk(fn):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    local.add(child.id)
                if isinstance(child, ast.ExceptHandler) and child.name:
                    local.add(child.name)
                if isinstance(child, ast.Lambda):
                    local.update(arg.arg for arg in (*child.args.posonlyargs, *child.args.args, *child.args.kwonlyargs))
            used = {
                child.id
                for child in ast.walk(fn)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id not in local
            }
            for decorator in fn.decorator_list:
                used.update(
                    child.id
                    for child in ast.walk(decorator)
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
                )
            missing.extend(sorted(used - available))

        self.assertEqual(
            sorted(set(missing)),
            [],
            'jcc_data_client_mixin.py uses names that are not imported. Re-run the extractor; '
            'do not add truncated method-body mixins.',
        )
