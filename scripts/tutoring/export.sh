#!/usr/bin/env bash
# EXPORT: build a scratch copy of the tree for evidence runs (PLAN section 0.7).
#
# A candidate export is `git archive <rev>` of the paths the checks need, with the
# lane's own changed files overlaid on top, so static checks, acceptance tests,
# scan suites and mutation proofs never see another lane's unfinished edits in
# the shared worktree. The export carries this script's siblings too, so every
# wrapper under <export>/scripts/tutoring/ judges the export, not the worktree.
#
#   export.sh <name> <rev> [--web] [--overlay <paths...>] [--delete <paths...>]
#   export.sh --print-paths [--web]     print the archive paths and exit
#
#   --web       also export web/ and link web/node_modules from this tree
#   --overlay   copy these working-tree files (with parent directories) on top
#   --delete    remove these files from the export (a lane's deletions)
#
# The export lands in .omc/exports/<name> (gitignored) with `.venv` symlinked to
# this tree's venv. It refuses an existing name, an unknown revision, a path that
# is absolute or contains `..`, and less than 10 GiB free on / (the lead lists and
# removes stale exports with `rm -r`). Everything is validated before anything is
# created, and a failed copy removes its own half-made directory.
#
# Test seams: TUTORING_EXPORTS_DIR (default <tree>/.omc/exports) and
# TUTORING_MIN_FREE_GIB (default 10).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# reports/ is deliberately absent: a whole-tree archive is about 910 MB.
# BUILD/review-rate-baseline.json is the one BUILD file the export needs:
# scripts/check_review_rate_gate.py (a STATIC step) reads it relative to its own
# tree and fails without it (PLAN section 0.7 omitted it).
ARCHIVE_PATHS=(
  lemely tests corpus scripts pyproject.toml alembic.ini docs/tutoring/SPEC.md
  BUILD/review-rate-baseline.json
)
USAGE="usage: export.sh <name> <rev> [--web] [--overlay <paths...>] [--delete <paths...>] | export.sh --print-paths [--web]"

refuse() {
  echo "export.sh: refusing: $*" >&2
  exit 2
}

usage_refuse() {
  refuse "$1
$USAGE"
}

if [ "${1:-}" = "--print-paths" ]; then
  shift
  web=0
  if [ "${1:-}" = "--web" ]; then
    web=1
    shift
  fi
  [ "$#" -eq 0 ] || usage_refuse "unexpected argument '$1'"
  printf '%s\n' "${ARCHIVE_PATHS[@]}"
  [ "$web" -eq 1 ] && echo web
  exit 0
fi

[ "$#" -ge 2 ] || usage_refuse "a name and a revision are required"
name="$1"
rev="$2"
shift 2

web=0
overlay=()
deletes=()
target=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --web)
      web=1
      target=""
      ;;
    --overlay)
      target="overlay"
      shift
      [ "$#" -gt 0 ] && [[ "$1" != --* ]] || usage_refuse "--overlay needs at least one path (overlay)"
      continue
      ;;
    --delete)
      target="delete"
      shift
      [ "$#" -gt 0 ] && [[ "$1" != --* ]] || usage_refuse "--delete needs at least one path (delete)"
      continue
      ;;
    --*) usage_refuse "unknown option '$1'" ;;
    *)
      case "$target" in
        overlay) overlay+=("$1") ;;
        delete) deletes+=("$1") ;;
        *) usage_refuse "unexpected argument '$1'" ;;
      esac
      ;;
  esac
  shift
done

# 1. Cheap validation: names and paths, no filesystem or git yet.
[[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] && [[ "$name" != *..* ]] ||
  refuse "invalid name '$name' (letters, digits, '.', '_' and '-', not starting with a symbol)"
[[ "$rev" != -* ]] || refuse "invalid revision '$rev'"

check_relative() {
  # check_relative <kind> <path>
  local kind="$1" p="$2"
  case "$p" in
    /*) refuse "$kind path '$p' is absolute; give a path relative to $ROOT" ;;
    .. | ../* | */../* | */..) refuse "$kind path '$p' contains a '..' segment" ;;
  esac
}
for p in ${overlay[@]+"${overlay[@]}"}; do
  check_relative overlay "$p"
  if [ "$web" -eq 0 ] && [[ "$p" == web/* ]]; then
    refuse "overlay path '$p' is under web/ but --web was not given"
  fi
done
for p in ${deletes[@]+"${deletes[@]}"}; do
  check_relative delete "$p"
done

# 2. Environment: disk and destination.
EXPORTS="${TUTORING_EXPORTS_DIR:-$ROOT/.omc/exports}"
dest="$EXPORTS/$name"
min_gib="${TUTORING_MIN_FREE_GIB:-10}"
case "$min_gib" in
  '' | *[!0-9]*) refuse "TUTORING_MIN_FREE_GIB must be a number, got '$min_gib'" ;;
esac
avail_kib="$(df -Pk / | awk 'NR==2 {print $4}')"
avail_gib=$((avail_kib / 1048576))
[ "$avail_gib" -ge "$min_gib" ] || refuse "only $avail_gib GiB free on /, need $min_gib (remove stale exports with rm -r)"
[ ! -e "$dest" ] || refuse "export '$name' already exists at $dest"
[ -e "$ROOT/.venv" ] || refuse "no .venv in $ROOT to link into the export"

# 3. Git: this must be a work tree root and the revision must exist.
top="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$top" ] && [ "$(cd "$top" && pwd -P)" = "$(pwd -P)" ] ||
  refuse "$ROOT is not the top of a git work tree (run export.sh from the worktree, not from an export)"
git -C "$ROOT" rev-parse --verify --quiet "$rev^{commit}" >/dev/null || refuse "unknown revision '$rev'"

# 4. Path content: overlay files must exist; delete paths must not be directories.
for p in ${overlay[@]+"${overlay[@]}"}; do
  [ -f "$ROOT/$p" ] || refuse "overlay path '$p' does not exist or is not a file in $ROOT"
done
for p in ${deletes[@]+"${deletes[@]}"}; do
  if [ -d "$ROOT/$p" ] || [ "$(git -C "$ROOT" cat-file -t "$rev:$p" 2>/dev/null || true)" = "tree" ]; then
    refuse "delete path '$p' is a directory; list its files"
  fi
done

# 5. Create. From here a failure removes the half-made export.
paths=("${ARCHIVE_PATHS[@]}")
[ "$web" -eq 1 ] && paths+=(web)

mkdir -p "$EXPORTS"
mkdir "$dest"
finished=0
cleanup() {
  if [ "$finished" -eq 0 ]; then
    rm -r -- "$dest"
    echo "export.sh: failed; removed the partial export $dest" >&2
  fi
}
trap cleanup EXIT

git -C "$ROOT" archive "$rev" "${paths[@]}" | tar -x -C "$dest"

for p in ${overlay[@]+"${overlay[@]}"}; do
  mkdir -p "$dest/$(dirname "$p")"
  cp -p "$ROOT/$p" "$dest/$p"
done
for p in ${deletes[@]+"${deletes[@]}"}; do
  rm -f -- "$dest/$p"
done

ln -s "$(readlink -f "$ROOT/.venv")" "$dest/.venv"
if [ "$web" -eq 1 ]; then
  if [ -e "$ROOT/web/node_modules" ]; then
    ln -s "$(readlink -f "$ROOT/web/node_modules")" "$dest/web/node_modules"
  else
    echo "export.sh: warning: $ROOT/web/node_modules is missing; web checks in the export need 'npm --prefix web ci' in the tree first" >&2
  fi
fi

finished=1
case "$dest" in
  "$ROOT"/*) shown="${dest#"$ROOT"/}" ;;
  *) shown="$dest" ;;
esac
echo "$shown"
echo "size: $(du -sh "$dest" | cut -f1) (revision $(git -C "$ROOT" rev-parse --short "$rev"), ${#overlay[@]} overlaid, ${#deletes[@]} deleted$([ "$web" -eq 1 ] && echo ', with web'))"
