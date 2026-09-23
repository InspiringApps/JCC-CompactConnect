"""Locate copied files and normalize their text for source comparison."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

COMMON_PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = COMMON_PYTHON_ROOT.parent.parent

_COPIED_FROM = re.compile(r'\A# Copied from (.+)\n(?:\n)?')
_METHOD_BODIES = re.compile(r'\A# Copied method bodies from (.+)\n(?:\n)?')
_IMPORT_START = re.compile(r'^(?:from\s+\S+\s+import\b|import\s+\S)')
_SKIP_DIR_NAMES = frozenset(
    {
        '__pycache__',
        '.ruff_cache',
        '.venv',
        # This test package is not a copy of Cosmetology/JCC sources.
        'copy_sync_tests',
    }
)
# Origin notes for fixture trees; not copied source files.
_SKIP_FILE_NAMES = frozenset({'README.md'})
_RESOURCE_TREE = COMMON_PYTHON_ROOT / 'lambdas' / 'common' / 'tests' / 'resources'
_COSMO_RESOURCE_TREE = (
    REPO_ROOT / 'backend' / 'cosmetology-app' / 'lambdas' / 'python' / 'common' / 'tests' / 'resources'
)
_JCC_MILITARY_AFFILIATION = (
    REPO_ROOT
    / 'backend'
    / 'compact-connect'
    / 'lambdas'
    / 'python'
    / 'common'
    / 'tests'
    / 'resources'
    / 'dynamo'
    / 'military-affiliation.json'
)


@dataclass(frozen=True)
class CopiedFile:
    dest: Path
    source: Path
    kind: str  # 'whole_file' | 'method_bodies'


def _iter_files(root: Path) -> Iterator[Path]:
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.name in _SKIP_FILE_NAMES:
            continue
        yield path


def _read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def parse_origin_comment(text: str) -> tuple[str, str, str] | None:
    """Return (kind, source_relpath, remainder) when the file declares a copy origin."""
    match = _METHOD_BODIES.match(text)
    if match:
        return 'method_bodies', match.group(1).strip(), text[match.end() :]
    match = _COPIED_FROM.match(text)
    if match:
        return 'whole_file', match.group(1).strip(), text[match.end() :]
    return None


def normalize_copied_body(body: str) -> str:
    """Reverse the mechanical package rename so a copy can be compared to its source."""
    return re.sub(r'\bcommon_lambdas\b', 'cc_common', body)


def strip_import_lines(text: str) -> str:
    """Drop import statements (including parenthesized multi-line imports) from file text."""
    kept: list[str] = []
    skipping_import = False
    paren_depth = 0
    for line in text.splitlines(keepends=True):
        if skipping_import:
            paren_depth += line.count('(') - line.count(')')
            if paren_depth <= 0:
                skipping_import = False
                paren_depth = 0
            continue
        if _IMPORT_START.match(line.lstrip()):
            paren_depth = line.count('(') - line.count(')')
            skipping_import = paren_depth > 0
            continue
        kept.append(line)
    # Removing mid-file re-export imports can leave extra blank lines; collapse those
    # so import-only additions do not fail the text comparison.
    return re.sub(r'\n{3,}', '\n\n', ''.join(kept))


def files_with_origin_comments() -> list[CopiedFile]:
    copied: list[CopiedFile] = []
    for dest in _iter_files(COMMON_PYTHON_ROOT):
        try:
            text = _read_text(dest)
        except UnicodeDecodeError:
            continue
        parsed = parse_origin_comment(text)
        if parsed is None:
            continue
        kind, source_relpath, _remainder = parsed
        copied.append(
            CopiedFile(
                dest=dest,
                source=REPO_ROOT / source_relpath,
                kind=kind,
            )
        )
    return copied


def _source_roots_by_dest_prefix(origin_files: list[CopiedFile]) -> dict[Path, set[Path]]:
    """Map each copied lambda/common_test prefix to the source trees its origin comments name."""
    roots: dict[Path, set[Path]] = {}
    for copied in origin_files:
        if copied.kind != 'whole_file':
            continue
        try:
            dest_rel = copied.dest.relative_to(COMMON_PYTHON_ROOT)
        except ValueError:
            continue
        parts = dest_rel.parts
        if parts[0] == 'lambdas' and len(parts) >= 2:
            dest_prefix = COMMON_PYTHON_ROOT / 'lambdas' / parts[1]
        elif parts[0] == 'common_test':
            dest_prefix = COMMON_PYTHON_ROOT / 'common_test'
        else:
            continue
        try:
            source_rel = copied.source.relative_to(REPO_ROOT)
        except ValueError:
            continue
        dest_suffix = copied.dest.relative_to(dest_prefix)
        source_prefix = REPO_ROOT / Path(*source_rel.parts[: len(source_rel.parts) - len(dest_suffix.parts)])
        roots.setdefault(dest_prefix, set()).add(source_prefix)
    return roots


def _uncommented_files_with_unique_source(origin_files: list[CopiedFile]) -> list[CopiedFile]:
    """Pair unmarked files (JSON fixtures, etc.) with a source path when exactly one origin tree has them."""
    extra: list[CopiedFile] = []
    origin_dests = {copied.dest.resolve() for copied in origin_files}
    for dest_prefix, source_prefixes in _source_roots_by_dest_prefix(origin_files).items():
        if not dest_prefix.is_dir():
            continue
        for dest in _iter_files(dest_prefix):
            if dest.resolve() in origin_dests:
                continue
            rel = dest.relative_to(dest_prefix)
            candidates = [prefix / rel for prefix in source_prefixes if (prefix / rel).is_file()]
            unique_sources: list[Path] = []
            seen_bytes: set[bytes] = set()
            for candidate in candidates:
                content = candidate.read_bytes()
                if content in seen_bytes:
                    continue
                seen_bytes.add(content)
                unique_sources.append(candidate)
            if len(unique_sources) != 1:
                continue
            extra.append(CopiedFile(dest=dest, source=unique_sources[0], kind='whole_file'))
    return extra


def _resource_tree_files() -> list[CopiedFile]:
    if not _RESOURCE_TREE.is_dir():
        return []
    copied: list[CopiedFile] = []
    for dest in _iter_files(_RESOURCE_TREE):
        rel = dest.relative_to(_RESOURCE_TREE)
        if rel.as_posix() == 'dynamo/military-affiliation.json':
            source = _JCC_MILITARY_AFFILIATION
        else:
            source = _COSMO_RESOURCE_TREE / rel
        copied.append(CopiedFile(dest=dest, source=source, kind='whole_file'))
    return copied


def all_copied_files() -> list[CopiedFile]:
    origin_files = files_with_origin_comments()
    by_dest: dict[Path, CopiedFile] = {copied.dest.resolve(): copied for copied in origin_files}
    for copied in _uncommented_files_with_unique_source(origin_files) + _resource_tree_files():
        by_dest.setdefault(copied.dest.resolve(), copied)
    return sorted(by_dest.values(), key=lambda copied: str(copied.dest))


def _text_for_compare(text: str, *, is_copy: bool) -> str:
    parsed = parse_origin_comment(text)
    body = text if parsed is None else parsed[2]
    if is_copy:
        body = normalize_copied_body(body)
    return strip_import_lines(body).strip()


def class_function_defs(source: str, class_name: str) -> dict[str, ast.AST]:
    tree = ast.parse(source)
    class_def = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name),
        None,
    )
    if class_def is None:
        raise ValueError(f'class {class_name} not found')
    return {node.name: node for node in class_def.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def function_source(text: str, node: ast.AST) -> str:
    """Return the function including decorators."""
    start = node.lineno
    decorator_list = getattr(node, 'decorator_list', [])
    if decorator_list:
        start = min(decorator.lineno for decorator in decorator_list)
    return ''.join(text.splitlines(keepends=True)[start - 1 : node.end_lineno])


def comparable_method_sources(copied: CopiedFile, *, dest_class: str, source_class: str) -> dict[str, tuple[str, str]]:
    """Map mixin method name -> (normalized dest source, source method source)."""
    dest_text = copied.dest.read_text(encoding='utf-8')
    source_text = copied.source.read_text(encoding='utf-8')
    dest_methods = class_function_defs(dest_text, dest_class)
    source_methods = class_function_defs(source_text, source_class)
    compared: dict[str, tuple[str, str]] = {}
    for name, dest_node in dest_methods.items():
        if name not in source_methods:
            raise KeyError(name)
        compared[name] = (
            normalize_copied_body(function_source(dest_text, dest_node)).strip(),
            function_source(source_text, source_methods[name]).strip(),
        )
    return compared


def comparable_contents(copied: CopiedFile) -> tuple[str | bytes, str | bytes]:
    """Return (normalized copy, source) for a whole-file copy.

    Text files are compared after stripping the origin comment and import lines.
    Files that are not valid UTF-8 are compared as raw bytes.
    """
    dest_bytes = copied.dest.read_bytes()
    source_bytes = copied.source.read_bytes()
    try:
        dest_text = dest_bytes.decode('utf-8')
        source_text = source_bytes.decode('utf-8')
    except UnicodeDecodeError:
        return dest_bytes, source_bytes
    return _text_for_compare(dest_text, is_copy=True), _text_for_compare(source_text, is_copy=False)
