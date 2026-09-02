#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

python3 -m compileall -q src tests examples
PYTHONPATH=src python3 -m unittest discover -s tests -v

if python3 -c 'import ruff' 2>/dev/null; then
  python3 -m ruff format --check .
  python3 -m ruff check .
else
  echo "ruff not installed; skipping format and lint checks"
fi

if python3 -c 'import mypy' 2>/dev/null; then
  python3 -m mypy
else
  echo "mypy not installed; skipping static type checks"
fi

verify_dir="$(mktemp -d "${TMPDIR:-/tmp}/promptquarry-verify.XXXXXX")"
trap 'rm -rf "$verify_dir"' EXIT

python3 examples/make_demo_export.py "$verify_dir/demo-export.zip" >/dev/null
PYTHONPATH=src python3 -m promptquarry.cli build \
  "$verify_dir/demo-export.zip" \
  --db "$verify_dir/quarry.sqlite3" >/dev/null
PYTHONPATH=src python3 -m promptquarry.cli summary "$verify_dir/quarry.sqlite3" >/dev/null
PYTHONPATH=src python3 -m promptquarry.cli review \
  "$verify_dir/quarry.sqlite3" --languages python >/dev/null
PYTHONPATH=src python3 -m promptquarry.cli extract \
  "$verify_dir/quarry.sqlite3" "$verify_dir/candidates" \
  --languages python --minimum-score 0 >/dev/null
test -s "$verify_dir/candidates/manifest.json"

mkdir -p "$verify_dir/wheels"
if python3 -c 'import setuptools.build_meta' 2>/dev/null; then
  PIP_NO_INDEX=1 python3 -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "$verify_dir/wheels" .
else
  python3 -m pip wheel --no-deps --wheel-dir "$verify_dir/wheels" .
fi

echo "All checks passed, including synthetic recovery and wheel creation."
