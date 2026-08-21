#!/usr/bin/env bash
# Isolated behavioural test for decide_session() + session_transcript(),
# extracted verbatim from the live supervisor so the test exercises the real
# code rather than a paraphrase of it.
set -u

SUP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/supervisor-accuracy.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# --- stand-ins for the supervisor's environment -----------------------------
HOME="$T/home"
REPO="$T/wt/accuracy"
STATEDIR="$T/state"
mkdir -p "$STATEDIR" "$REPO"
SESSIONFILE="$STATEDIR/session_id"
RESUME_CHAINFILE="$STATEDIR/resume_chain"
TIMEOUTFILE="$STATEDIR/last_timeout"
MAX_RESUME_CHAIN=6
run=7

SLUG="$(printf '%s' "$REPO" | tr -c 'a-zA-Z0-9' '-')"
mkdir -p "$HOME/.claude/projects/$SLUG"

# --- the code under test, lifted from the supervisor ------------------------
eval "$(awk '/^new_session_id\(\) \{/,/^}/' "$SUP")"
eval "$(awk '/^session_transcript\(\) \{/,/^}/' "$SUP")"
eval "$(awk '/^decide_session\(\) \{/,/^}/' "$SUP")"

pass=0; fail=0
check() { # check <label> <expected: RESUME|COLD> [expected-sid]
  local label="$1" want="$2" wantsid="${3:-}" got
  decide_session >/dev/null
  got=$([ -n "$RESUME_SID" ] && echo RESUME || echo COLD)
  if [ "$got" = "$want" ] && { [ -z "$wantsid" ] || [ "$RESUME_SID" = "$wantsid" ]; }; then
    pass=$((pass + 1)); printf '  PASS  %-52s -> %s\n' "$label" "$got"
  else
    fail=$((fail + 1)); printf '  FAIL  %-52s -> %s (wanted %s%s)\n' \
      "$label" "$got" "$want" "${wantsid:+ / $wantsid}"
  fi
}

seed() { # seed <sid> <chain>; creates the transcript so it looks real
  echo "$1" > "$SESSIONFILE"; echo "$2" > "$RESUME_CHAINFILE"
  : > "$(session_transcript "$1")"
  LAST_RC=0; LAST_LIMITED=0; rm -f "$TIMEOUTFILE"
}

SID="aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"

echo "== session_transcript path derivation =="
want="$HOME/.claude/projects/$SLUG/$SID.jsonl"
if [ "$(session_transcript "$SID")" = "$want" ]; then
  pass=$((pass + 1)); echo "  PASS  slug matches claude's project-dir convention"
else
  fail=$((fail + 1)); echo "  FAIL  got $(session_transcript "$SID")"; echo "        want $want"
fi

echo "== decide_session =="
LAST_RC=0; LAST_LIMITED=0; rm -f "$SESSIONFILE" "$RESUME_CHAINFILE" "$TIMEOUTFILE"
check "no session recorded (run 1)" COLD

seed "$SID" 0
check "clean previous run, chain 0" RESUME "$SID"

seed "$SID" 5
check "chain 5 of 6 — still under the cap" RESUME "$SID"

seed "$SID" 6
check "chain 6 of 6 — cap reached, shed context" COLD

seed "$SID" 0; touch "$TIMEOUTFILE"
check "previous run hit the background-task ceiling" COLD

seed "$SID" 0; LAST_RC=1
check "previous run crashed (rc=1)" COLD

seed "$SID" 0; LAST_LIMITED=1
check "previous run stopped on a usage limit" COLD

seed "$SID" 0; rm -f "$(session_transcript "$SID")"
check "recorded session has no transcript on disk" COLD

seed "$SID" abc
check "corrupt chain counter treated as 0" RESUME "$SID"

echo "== new_session_id =="
u="$(new_session_id)"
if printf '%s' "$u" | grep -qE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'; then
  pass=$((pass + 1)); echo "  PASS  mints a well-formed uuid ($u)"
else
  fail=$((fail + 1)); echo "  FAIL  malformed uuid: $u"
fi
if [ "$(new_session_id)" != "$u" ]; then
  pass=$((pass + 1)); echo "  PASS  successive ids differ"
else
  fail=$((fail + 1)); echo "  FAIL  same id twice"
fi

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
