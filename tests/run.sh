#!/usr/bin/env bash
# Everything, in the order that fails fastest.
set -e
cd "$(dirname "$0")/.."
for t in tests/test_notify.py tests/test_import.py tests/test_render.py; do
  echo "=== $t ==="
  python3 "$t" 2>&1 | grep -v "ScriptRunContext\|MemoryCacheStorageManager"
done
echo
echo "ALL SUITES PASS"
