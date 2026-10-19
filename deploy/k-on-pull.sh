#!/usr/bin/env bash
# Pull-based deployment: checks the GitHub release "server-build" for a new bundle and, when one appears,
# verifies its checksum and hands it to /usr/local/sbin/k-on-deploy (backup, migrate, restart, rollback).
# Run by k-on-pull.timer every 2 minutes. Nothing connects to this server from outside.
set -euo pipefail

REPO=${K_ON_REPO:-Lin-Kumiko/K-ON-office}
BASE="https://github.com/$REPO/releases/download/server-build"
STATE=/var/lib/k-on-deploy
PROXY=${K_ON_PROXY:-http://127.0.0.1:7890}
mkdir -p "$STATE"
chmod 700 "$STATE"

fetch() {  # fetch URL OUT: through the local proxy first (GitHub is slow from CN), then direct
  curl -fsSL --retry 2 --connect-timeout 10 --max-time 300 --proxy "$PROXY" -o "$2" "$1" 2>/dev/null \
    || curl -fsSL --retry 2 --connect-timeout 15 --max-time 600 -o "$2" "$1"
}

TMP=$(mktemp -d /tmp/k-on-pull.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

if ! fetch "$BASE/version.txt" "$TMP/version.txt"; then
  echo "[k-on-pull] no release metadata yet (or GitHub unreachable)"
  exit 0
fi
# version.txt: "<commit sha> <sha256 of release.tgz>"
read -r SHA SUM < "$TMP/version.txt"
[[ "$SHA" =~ ^[0-9a-f]{40}$ && "$SUM" =~ ^[0-9a-f]{64}$ ]] || { echo "[k-on-pull] malformed version.txt"; exit 1; }

CURRENT=$(cat "$STATE/current" 2>/dev/null || true)
FAILED=$(cat "$STATE/failed" 2>/dev/null || true)
[ "$SHA" = "$CURRENT" ] && exit 0
[ "$SHA" = "$FAILED" ] && exit 0   # do not retry a release that already failed; the next push gets a new sha

echo "[k-on-pull] new release ${SHA:0:7} (current ${CURRENT:0:7})"
fetch "$BASE/release.tgz" "$TMP/release.tgz"
echo "$SUM  $TMP/release.tgz" | sha256sum -c --status || { echo "[k-on-pull] checksum mismatch, skipped"; exit 1; }

if /usr/local/sbin/k-on-deploy < "$TMP/release.tgz"; then
  echo "$SHA" > "$STATE/current"
  rm -f "$STATE/failed"
  echo "[k-on-pull] release ${SHA:0:7} deployed"
else
  echo "$SHA" > "$STATE/failed"
  echo "[k-on-pull] release ${SHA:0:7} failed and was rolled back"
  exit 1
fi
