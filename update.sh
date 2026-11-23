#!/usr/bin/env bash
# Rebuild the Midori report viewer from reports.json and push to GitHub Pages.
# Usage:
#   MIDORI_GH_TOKEN=... ./update.sh
# Expects reports.json to already contain the new report entry.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ -z "${MIDORI_GH_TOKEN:-}" ]; then
  echo "error: MIDORI_GH_TOKEN is not set" >&2
  exit 1
fi

python3 build.py

# Stage only the daily artifacts (not screenshots or local junk).
git add -- reports.json index.html sw.js manifest.json template.html summary.py v2.py update.sh \
  icon-180.png icon-192.png icon-512.png icon-512-maskable.png \
  apple-touch-icon.png og.png build.py README.md

if git diff --cached --quiet; then
  echo "No changes to commit"
  exit 0
fi

DATE="$(python3 -c "import json; print(max(r['date'] for r in json.load(open('reports.json'))))")"
git commit -m "${COMMIT_MSG:-Add report ${DATE}}"

# Push with the token from the environment. Do not write it into the remote URL,
# git config, or any committed file. Disable tracing so the header is not logged.
unset GIT_TRACE GIT_CURL_VERBOSE GIT_TRACE_PACKET GIT_TRACE_CURL GIT_TRACE_SETUP
export GIT_TERMINAL_PROMPT=0
git -c credential.helper= \
    -c credential.helper='!f() { printf "username=x-access-token\npassword=%s\n" "$MIDORI_GH_TOKEN"; }; f' \
    push origin main

echo "Pushed update for ${DATE}"
