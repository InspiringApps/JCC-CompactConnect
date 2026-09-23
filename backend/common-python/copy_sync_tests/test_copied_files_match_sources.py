"""Copied-file drift checks for backend/common-python.

Most copies are whole files from Cosmetology or JCC. Those are compared as text
(origin comment and import lines ignored) so neither source app nor PSYPACT can
silently edit a "shared" file.

Each WHOLE_FILE_COMPARE_EXCLUSIONS path needs its own test file. Do not collect
mixed-lineage files into one module. The DataClient mixin is checked in
test_jcc_data_client_mixin.py.
"""

import ast
import difflib
import unittest

from copy_sync_tests.copied_file_text import (
    COMMON_PYTHON_ROOT,
    REPO_ROOT,
    all_copied_files,
    comparable_contents,
    parse_origin_comment,
)

# Paths relative to backend/common-python. Every discovered copy not in this list is compared
# to its source. Add a new entry when a file cannot be a verbatim copy, and describe the
# cross-project need that prevents copying complete source files, and combining multiple. Each entry
# also needs its own test file (Ex. see test_jcc_data_client_mixin.py).
WHOLE_FILE_COMPARE_EXCLUSIONS: frozenset[str] = frozenset(
    {
        # PSYPACT licensing/encumbrance uses Cosmetology DataClient (read-time privileges).
        # Selected JCC handlers need JCC DataClient methods on the same instance.
        # JCC data_client.py would restore stored-privilege behavior, so only those method
        # bodies are composed onto Cosmetology DataClient. Tests:
        # test_jcc_data_client_mixin.py.
        'common_lambdas/data_model/jcc_data_client_mixin.py',
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


def _late_shadowing_imports(source: str) -> list[str]:
    """Names defined in a file then re-imported later (the old Cosmetology+JCC splice pattern)."""
    parsed = parse_origin_comment(source)
    body = source if parsed is None else parsed[2]
    tree = ast.parse(body)
    defined: set[str] = set()
    seen_definition = False
    shadows: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            seen_definition = True
            defined.add(node.name)
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
            continue
        if isinstance(node, ast.ImportFrom) and seen_definition:
            for alias in node.names:
                imported = alias.asname or alias.name
                if imported in defined:
                    shadows.append(imported)
    return shadows


class TestCopiedFilesMatchSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.copied_files = all_copied_files()

    def _dest_rel(self, copied) -> str:
        return copied.dest.relative_to(COMMON_PYTHON_ROOT).as_posix()

    def test_copied_files_were_discovered(self):
        """Scanner found enough copies that a broken origin-comment walk cannot pass silently."""
        whole_files = [
            copied for copied in self.copied_files if self._dest_rel(copied) not in WHOLE_FILE_COMPARE_EXCLUSIONS
        ]
        self.assertGreater(
            len(whole_files),
            100,
            'Expected to discover copied files via origin comments and source-tree counterparts.',
        )

    def test_copy_origin_sources_exist(self):
        """Every `# Copied from …` / `# Copied method bodies from …` path still exists in the repo."""
        missing = [
            f'{self._dest_rel(copied)} -> {copied.source}'
            for copied in self.copied_files
            if not copied.source.is_file()
        ]
        self.assertEqual(missing, [], 'Copied files declare a source path that does not exist.')

    def test_exclusions_are_documented_copied_files(self):
        """WHOLE_FILE_COMPARE_EXCLUSIONS only lists real copies; stale paths would skip nothing."""
        discovered = {self._dest_rel(copied) for copied in self.copied_files}
        missing = sorted(WHOLE_FILE_COMPARE_EXCLUSIONS - discovered)
        self.assertEqual(
            missing,
            [],
            'WHOLE_FILE_COMPARE_EXCLUSIONS entries must exist as discovered copies; '
            'remove stale paths or they will hide an incomplete scan.',
        )

    def test_method_body_copies_are_explicitly_excluded(self):
        """Partial copies (method-body mixins) cannot use whole-file compare; they must be excluded by path."""
        mixins = {self._dest_rel(copied) for copied in self.copied_files if copied.kind == 'method_bodies'}
        undeclared = sorted(mixins - WHOLE_FILE_COMPARE_EXCLUSIONS)
        self.assertEqual(
            undeclared,
            [],
            'Mixin copies (kind=method_bodies) must be listed in WHOLE_FILE_COMPARE_EXCLUSIONS '
            'with a reason; they are not whole-file copies.',
        )

    def test_whole_file_copies_do_not_shadow_names_with_late_imports(self):
        """A whole-file copy must not re-import a name after defining it (that hides mixed-lineage splices)."""
        shadows: list[str] = []
        for copied in self.copied_files:
            if self._dest_rel(copied) in WHOLE_FILE_COMPARE_EXCLUSIONS:
                continue
            if copied.dest.suffix != '.py':
                continue
            try:
                text = copied.dest.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            found = _late_shadowing_imports(text)
            if found:
                shadows.append(f'{self._dest_rel(copied)}: {", ".join(found)}')
        self.assertEqual(
            shadows,
            [],
            'Whole-file copies must not re-import names that replace classes already defined '
            'in the file. Import the other lineage from its own module instead.',
        )

    def test_every_whole_file_copy_matches_its_source_text(self):
        """Every non-excluded copy still matches its Cosmetology or JCC source after allowed header/import diffs."""
        mismatches: list[str] = []
        for copied in self.copied_files:
            if self._dest_rel(copied) in WHOLE_FILE_COMPARE_EXCLUSIONS:
                continue
            if not copied.source.is_file():
                continue
            copy_contents, source_contents = comparable_contents(copied)
            if copy_contents == source_contents:
                continue
            dest_rel = self._dest_rel(copied)
            try:
                source_rel = copied.source.relative_to(REPO_ROOT)
            except ValueError:
                source_rel = copied.source
            mismatches.append(
                f'{dest_rel} != {source_rel}\n'
                + _unified_diff(
                    source_contents,
                    copy_contents,
                    str(source_rel),
                    str(dest_rel),
                )
            )

        self.assertEqual(
            [],
            [mismatch.split('\n', 1)[0] for mismatch in mismatches],
            'Copied files drifted from their sources. Allowed differences are the origin '
            'comment and import lines (including cc_common -> common_lambdas). '
            'Treat the copy like a semantically versioned package: do not change it unless the '
            'change is backwards compatible with existing cross-compact consumers of the file. '
            'If the source change is compatible (additive methods/fields, bugfixes that preserve '
            'current contracts), re-copy the file. If it is breaking (removed/renamed APIs, newly '
            'required fields, changed return shapes or side effects), do not update the shared file; '
            'keep the old contract and put the new behavior in a wrapper, subclass, or new module. '
            'If a consumer edited the copy, restore it from the source instead. '
            'If a file cannot be a verbatim copy, add it to WHOLE_FILE_COMPARE_EXCLUSIONS '
            'with a comment explaining why - this should be rare.\n\n' + '\n\n'.join(mismatches),
        )
