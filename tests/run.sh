#!/usr/bin/env bash
# Everything, fastest-failing first.
# pipefail matters: each suite is piped through grep to drop Streamlit's
# noise, and without it the pipeline's status is grep's. A failing suite
# printed its traceback and the run still ended "ALL SUITES PASS".
set -eo pipefail
cd "$(dirname "$0")/.."
for t in tests/test_splash.py tests/test_espn.py tests/test_store.py \
         tests/test_model.py tests/test_simulate.py tests/test_watch.py tests/test_notify.py \
         tests/test_load.py tests/test_app.py; do
  echo "=== $t ==="
  python3 "$t" 2>&1 | grep -v "ScriptRunContext\|MemoryCacheStorageManager"
done
echo
echo "ALL SUITES PASS"
