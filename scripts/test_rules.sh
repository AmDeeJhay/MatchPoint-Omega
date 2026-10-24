#!/bin/sh
# Run the MeTTa rules outside Omega with PeTTa, to check matching logic.
# Usage: PETTA=/path/to/PeTTa sh scripts/test_rules.sh
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PETTA=${PETTA:-$HOME/PeTTa}
TMP=$(mktemp -d)
# Drop Omega-only lines (Python bridge import) so the rules load standalone.
grep -v "library Omega" "$ROOT/omega-plugin/tennis/tennis.metta" > "$TMP/tennis_core.metta"
{ echo "!(import! &plugin-tennis $TMP/tennis_core)"; cat "$ROOT/tests/rules_test.metta"; } > "$TMP/run.metta"
cd "$PETTA" && sh run.sh "$TMP/run.metta" 2>&1 | grep -v '^\s*$' | grep -v '^.\[3[36]m\|^.\[35m\|^:-\|^\s' | tail -40
