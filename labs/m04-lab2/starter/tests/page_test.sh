#!/usr/bin/env bash
# The page starts with the banner from @textkit and ends with the title.
set -euo pipefail
page="$1"
[[ "$(head -n 1 "$page")" == "== The Handbook ==" ]] || { echo "bad banner"; cat "$page"; exit 1; }
[[ "$(tail -n 1 "$page")" == "Getting started" ]] || { echo "bad title"; cat "$page"; exit 1; }
echo "page ok"
