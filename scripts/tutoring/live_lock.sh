#!/usr/bin/env bash
# LIVE lock: the machine-wide mutex for live-stack runs (PLAN section 0.9, step 1).
#
# Playwright and the Puppeteer audit share one local stack (ports 8000 and 5173,
# GoTrue, Storage). The lock is an atomically created directory holding the
# owner, the worktree and the time. Other sessions do not know this lock; it
# serialises this build only. live_e2e.sh and live_audit.sh refuse to run
# unless the lock exists and was taken from the same worktree.
#
# Usage: bash scripts/tutoring/live_lock.sh acquire <owner>
#        bash scripts/tutoring/live_lock.sh release <owner>
#        bash scripts/tutoring/live_lock.sh status
#
# TUTORING_LIVE_LOCK overrides the lock path (default
# /home/sico/Code/Lemely/.omc/state/tutoring-live.lock).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

LOCK="${TUTORING_LIVE_LOCK:-/home/sico/Code/Lemely/.omc/state/tutoring-live.lock}"
WORKTREE="$(pwd -P)"

refuse() {
  echo "live_lock.sh: refusing: $*" >&2
  exit 2
}

field() {
  # field <name>: one recorded value, or "unknown".
  cat "$LOCK/$1" 2>/dev/null || echo unknown
}

check_owner() {
  [ "$#" -eq 1 ] || refuse "an owner name is required"
  [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]] || refuse "owner '$1' must be letters, digits, '.', '_' or '-'"
}

[ "$#" -ge 1 ] || refuse "usage: live_lock.sh acquire <owner> | release <owner> | status"
command="$1"
shift

case "$command" in
  acquire)
    check_owner "$@"
    mkdir -p "$(dirname "$LOCK")"
    if mkdir "$LOCK" 2>/dev/null; then
      printf '%s\n' "$1" >"$LOCK/owner"
      printf '%s\n' "$WORKTREE" >"$LOCK/worktree"
      date -u +%Y-%m-%dT%H:%M:%SZ >"$LOCK/acquired_at"
      echo "live_lock.sh: acquired $LOCK for $1"
    else
      refuse "lock held by $(field owner) for worktree $(field worktree) since $(field acquired_at)"
    fi
    ;;
  release)
    check_owner "$@"
    [ -d "$LOCK" ] || refuse "no lock at $LOCK"
    [ "$(field owner)" = "$1" ] || refuse "lock is held by $(field owner), not $1"
    rm -r -- "$LOCK"
    echo "live_lock.sh: released $LOCK"
    ;;
  status)
    [ "$#" -eq 0 ] || refuse "status takes no arguments"
    if [ -d "$LOCK" ]; then
      echo "held by $(field owner) worktree=$(field worktree) since $(field acquired_at)"
    else
      echo "free ($LOCK)"
    fi
    ;;
  *)
    refuse "unknown command '$command' (acquire | release | status)"
    ;;
esac
