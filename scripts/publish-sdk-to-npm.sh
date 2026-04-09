#!/usr/bin/env bash
# Publish natural-path-sdk (unscoped) to the public npm registry.
# Usage (use a NEW token; never commit or paste tokens into chat):
#   export NODE_AUTH_TOKEN="npm_xxxxx"
#   ./backend/scripts/publish-sdk-to-npm.sh
#
# Requires: any npm account (no org/@scope needed for this package name).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SDK="$ROOT/sdk"
TOKEN="${NODE_AUTH_TOKEN:-${NPM_TOKEN:-}}"

if [[ -z "$TOKEN" ]]; then
  echo "Set NODE_AUTH_TOKEN or NPM_TOKEN in your environment (Automation token from npmjs.com)." >&2
  exit 1
fi

cd "$SDK"
npm ci
npm run build

TMP_NPMRC="$(mktemp)"
cleanup() { rm -f "$TMP_NPMRC"; }
trap cleanup EXIT

printf '%s\n' \
  'registry=https://registry.npmjs.org/' \
  "//registry.npmjs.org/:_authToken=${TOKEN}" \
  >"$TMP_NPMRC"

npm publish --access public --userconfig "$TMP_NPMRC"

echo "Published. Verify: npm view natural-path-sdk version"
