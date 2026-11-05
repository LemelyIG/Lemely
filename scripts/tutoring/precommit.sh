#!/usr/bin/env bash
# PRE-COMMIT: run the repo's pre-commit hooks the way the tutoring build needs.
#
#   --files <paths...>   lanes: ruff, ruff-format and the file hooks on the given
#                        files only. mypy, pyright and import-linter are skipped
#                        (SKIP=mypy,pyright,import-linter) because in the shared
#                        worktree they would judge other lanes' unfinished files;
#                        the lane runs them on its candidate export instead
#                        (static.sh).
#   --all-files          lead: every hook except pyright (SKIP=pyright), then the
#                        pyright step of static.sh with this tree's extraPaths.
#
# `pre-commit run --files` and `--all-files` never stash (checked in pre-commit's
# source), so another lane's unstaged work is not touched. The ruff hook runs
# `--fix`: an autofix is a finding, read `git diff` before committing. Both modes
# end with `git status --short`.
#
# TUTORING_DRY_RUN=1 prints `DRY-RUN <argv>` (and `DRY-RUN-NEXT <argv>` for the
# pyright step) instead of running them.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

refuse() {
  echo "precommit.sh: refusing: $*" >&2
  exit 2
}

mode=""
paths=()
case "${1:-}" in
  --files)
    mode="files"
    shift
    [ "$#" -gt 0 ] || refuse "--files needs at least one path"
    for p in "$@"; do
      case "$p" in
        -*) refuse "unknown option '$p' (usage: precommit.sh --files <paths...> | --all-files)" ;;
      esac
      paths+=("$p")
    done
    ;;
  --all-files)
    mode="all"
    shift
    [ "$#" -eq 0 ] || refuse "--all-files takes no further arguments"
    ;;
  *)
    refuse "usage: precommit.sh --files <paths...> | --all-files"
    ;;
esac

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || refuse "not inside a git work tree"

export PATH="$ROOT/.venv/bin:$PATH"
PRE_COMMIT="$ROOT/.venv/bin/pre-commit"

emit() {
  # emit <label> <argv...>: print the command (dry run) or run it.
  local label="$1"
  shift
  if [ "${TUTORING_DRY_RUN:-}" = "1" ]; then
    printf '%s' "$label"
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

rc=0
if [ "$mode" = "files" ]; then
  existing=()
  for p in "${paths[@]}"; do
    if [ -e "$p" ]; then
      existing+=("$p")
    else
      echo "precommit.sh: skipping $p (does not exist)" >&2
    fi
  done
  [ "${#existing[@]}" -gt 0 ] || refuse "none of the given paths exist"
  emit DRY-RUN env SKIP=mypy,pyright,import-linter "$PRE_COMMIT" run --files "${existing[@]}" || rc=$?
else
  emit DRY-RUN env SKIP=pyright "$PRE_COMMIT" run --all-files || rc=$?
  step_rc=0
  emit DRY-RUN-NEXT bash "$ROOT/scripts/tutoring/static.sh" --only pyright || step_rc=$?
  if [ "$step_rc" -ne 0 ]; then
    rc="$step_rc"
  fi
fi

echo "== git status --short"
git status --short
if [ "$rc" -ne 0 ]; then
  echo "precommit.sh: failed (exit $rc); an autofix may have rewritten files, see git status above" >&2
  exit "$rc"
fi
