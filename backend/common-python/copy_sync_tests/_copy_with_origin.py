#!/usr/bin/env python3
"""Copy a source file into common-python with origin comment and package rename."""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMON_PYTHON = REPO_ROOT / 'backend' / 'common-python'


def copy_with_origin(src_rel: str, dst_rel: str) -> None:
    src = REPO_ROOT / src_rel
    dst = COMMON_PYTHON / dst_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    body = src.read_text(encoding='utf-8')
    body = body.replace('cc_common', 'common_lambdas')
    dst.write_text(f'# Copied from {src_rel}\n\n{body}', encoding='utf-8')
    print(f'copied {src_rel} -> {dst_rel}')  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('src_rel')
    parser.add_argument('dst_rel')
    args = parser.parse_args()
    copy_with_origin(args.src_rel, args.dst_rel)


if __name__ == '__main__':
    main()
