#!/usr/bin/env python3
"""Extract selected JCC DataClient methods into the PSYPACT DataClient mixin."""

from __future__ import annotations

import ast
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
JCC_DATA_CLIENT = REPO_ROOT / 'backend/compact-connect/lambdas/python/common/cc_common/data_model/data_client.py'
COSMO_DATA_CLIENT = REPO_ROOT / 'backend/cosmetology-app/lambdas/python/common/cc_common/data_model/data_client.py'
DEST = REPO_ROOT / 'backend/common-python/common_lambdas/data_model/jcc_data_client_mixin.py'

ROOT_METHODS = {
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

# Cosmetology owns these module paths; JCC types used by extracted methods live here instead.
MODULE_REWRITES = {
    'common_lambdas.data_model.schema.privilege': 'common_lambdas.data_model.schema.privilege.jcc_data',
    'common_lambdas.data_model.schema.provider': 'common_lambdas.data_model.schema.provider.jcc_provider',
}
NAME_MODULE_OVERRIDES = {
    'ProviderRecordType': 'common_lambdas.psypact_records',
}

ORIGIN = (
    '# Copied method bodies from backend/compact-connect/lambdas/python/common/'
    'cc_common/data_model/data_client.py\n'
    '# ruff: noqa: C901, PLR0915, PLR0912, ARG002\n'
)


def _self_calls(fn: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'self'
        ):
            names.add(node.func.attr)
    return names


def _load_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)}


def _rewrite_module(module: str) -> str:
    module = module.replace('cc_common', 'common_lambdas')
    return MODULE_REWRITES.get(module, module)


def _format_from_import(module: str, aliases: list[tuple[str, str | None]]) -> str:
    parts = [f'{name} as {asname}' if asname else name for name, asname in aliases]
    if len(parts) == 1 and len(f'from {module} import {parts[0]}') <= 120:
        return f'from {module} import {parts[0]}\n'
    inner = ',\n'.join(f'    {part}' for part in parts)
    return f'from {module} import (\n{inner},\n)\n'


def _header_for(tree: ast.Module, used: set[str], source_lines: list[str]) -> str:
    import_blocks: list[str] = []
    from_blocks: OrderedDict[str, list[tuple[str, str | None]]] = OrderedDict()
    constants: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            kept = [alias for alias in node.names if (alias.asname or alias.name.split('.')[0]) in used]
            if not kept:
                continue
            import_blocks.append(
                'import ' + ', '.join(f'{a.name} as {a.asname}' if a.asname else a.name for a in kept) + '\n'
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                if local not in used:
                    continue
                module = NAME_MODULE_OVERRIDES.get(local, _rewrite_module(node.module))
                from_blocks.setdefault(module, []).append((alias.name, alias.asname))
        elif isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if names and all(name in used for name in names):
                constants.append(''.join(source_lines[node.lineno - 1 : node.end_lineno]))

    chunks = [ORIGIN]
    if import_blocks:
        chunks.extend(import_blocks)
        chunks.append('\n')
    for module, aliases in from_blocks.items():
        chunks.append(_format_from_import(module, aliases))
    if from_blocks:
        chunks.append('\n')
    if constants:
        chunks.extend(constants)
        chunks.append('\n')
    chunks.append('\nclass JccDataClientMixin:\n')
    return ''.join(chunks)


def main() -> None:
    source = JCC_DATA_CLIENT.read_text(encoding='utf-8')
    tree = ast.parse(source)
    class_def = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'DataClient')
    methods = {node.name: node for node in class_def.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    cosmo_tree = ast.parse(COSMO_DATA_CLIENT.read_text(encoding='utf-8'))
    cosmo_class = next(node for node in cosmo_tree.body if isinstance(node, ast.ClassDef) and node.name == 'DataClient')
    cosmo_methods = {
        node.name for node in cosmo_class.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    needed: set[str] = set()
    stack = list(ROOT_METHODS)
    while stack:
        name = stack.pop()
        if name in needed:
            continue
        if name not in methods:
            continue
        # Cosmetology DataClient already supplies these; keep MRO on the Cosmetology base.
        if name in cosmo_methods:
            continue
        needed.add(name)
        stack.extend(_self_calls(methods[name]) - cosmo_methods)

    ordered = sorted(needed, key=lambda name: methods[name].lineno)
    extracted = [methods[name] for name in ordered]
    used: set[str] = set()
    for fn in extracted:
        used |= _load_names(fn)
        for decorator in fn.decorator_list:
            used |= _load_names(decorator)

    lines = source.splitlines(keepends=True)
    chunks: list[str] = []
    for name in ordered:
        node = methods[name]
        start = node.lineno - 1
        while start > 0 and lines[start - 1].lstrip().startswith('@'):
            start -= 1
        chunk = ''.join(lines[start : node.end_lineno])
        chunk = chunk.replace('cc_common', 'common_lambdas')
        chunks.append(chunk.rstrip() + '\n')

    DEST.write_text(_header_for(tree, used, lines) + '\n'.join(chunks), encoding='utf-8')
    print(f'wrote {DEST} with {len(ordered)} methods: {", ".join(ordered)}')  # noqa: T201


if __name__ == '__main__':
    main()
