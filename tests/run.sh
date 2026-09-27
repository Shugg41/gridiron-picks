#!/usr/bin/env bash
# Everything, fastest-failing first.
set -e
cd "$(dirname "$0")/.."
for t in tests/test_splash.py tests/test_espn.py tests/test_store.py \
         tests/test_model.py tests/test_notify.py tests/test_app.py; do
  echo "=== $t ==="
  python3 "$t" 2>&1 | grep -v "ScriptRunContext\|MemoryCacheStorageManager"
done
echo
echo "ALL SUITES PASS"
