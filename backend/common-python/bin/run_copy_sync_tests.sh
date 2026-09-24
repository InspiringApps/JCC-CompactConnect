#!/bin/bash
# Compare backend/common-python copies with their Cosmetology/JCC sources.
# Stdlib only; run from any working directory.
set -euo pipefail

cd "$(dirname "$0")/.."
echo "Running common-python copy-sync tests..."
python3 -m unittest discover -s copy_sync_tests -t . "$@"
