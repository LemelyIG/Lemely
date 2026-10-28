# ADR-T04: Past-student outcome statistics on a tutor profile

**Status:** Accepted (rows 8, 8b and 13 of `BUILD/tutoring/decision-log.md`, locked 2026-10-25). Rows 8 and 13 were chosen by the user **against the architect's recommendation**; the risks are recorded below as accepted, with the controls in force.
**Date:** 2026-10-25 (rev 2 after `THREAT-MODEL.md` and `ADVERSARIAL-SPEC.md`)
**Deciders:** Product owner (user); architect

## Context

Students choosing a tutor want evidence of results. Lemely holds marked
past-paper attempts per student (`attempts`, `PaperRecord`), so it can
aggregate the grades of a tutor's past students. Five facts constrain this:

1. **Grades are ordinal.** `GRADE_ORDER = ["A*", "A", "B", "C", "D", "E", "U"]`
   (`lemely/core/history.py:31`); `is_grade_bearing` drops anything else
   (`:80-92`). A pie chart and any mean of grades are wrong for ordinal data.
2. **Marking is not examiner-accurate** (DELIVERY §5.1), and a grade computed
   from an estimated boundary (`attempts.boundary_source` `subject_default` or
   `global_default`, `lemely/db/models/enums.py:141-146`) is an estimate that UI
   principle 6 requires to be labelled every time.
3. **Students choose tutors.** A before/after difference is not caused by the
   tutor.
4. **Grades are private** (MISSION §3). Aggregates of a small group can
   identify individuals.
5. **The tutor is a privileged observer** (THREAT-MODEL OS-2/OS-3, ADVERSARIAL
   F1). The tutor knows every cohort member by name, holds exact grades of the
   members who granted access, controlled (in the first revision) the moment
   each member joined by marking a booking completed, and can read the figure
   on demand (T8, SP4). k ≥ 5 limits how small the set is, not how small a
   change is.

## Decision

Show, per tutor and subject, on the logged-in profile only (row 5b):

1. **Grade distribution:** a horizontal stacked bar over the recorded ladder,
   in ladder order, each segment labelled, `n` stated, table alternative.
2. **"Change in grade while with this tutor":** how many students had a
   *higher*, the *same*, or a *lower* grade than before (the higher/same/lower
   reading of row 8 is approved, row 15e), `n` stated, table alternative.
   Never the word "improvement".
3. **Counted by default, one-tap opt-out** (row 8), with notices at booking,
   after completion and next to the toggle.
4. **Caveat on every figure** (marking, selection, estimated boundaries left
   out, the window in days).
5. **Computed live on every request** (row 13: no monthly as-of snapshot), with
   the membership, window and suppression rules below.

### Definitions (pure, in `lemely/core/tutor_outcomes.py`; SQL in `tutor_directory_repo`)

- **Counted session** for (tutor, subject, student): a booking with
  `accepted_at IS NOT NULL`, `state IN ('accepted','completed','no_show')` and
  `ends_at <= now()`. The tutor's outcome marks (`completed`, `no_show`), a
  student's or parent's completion claim, an admin dispute resolution and a
  **tutor-initiated** block change nothing here. Cancelling is only possible
  before a session starts.
- **S** = start of the student's first counted session in the subject. It is
  fixed once that session has ended, and nothing anyone does afterwards moves it.
- **Window and close instant:** the during-window is `[S, S + DURING_WINDOW)`
  with `DURING_WINDOW = 120 days`; the member **closes** at `C = S + 120 days`.
  Later sessions never reopen it. (Rev 1 used `[S, E + 60 d]` with `E` the end
  of the last session; that let a new session drop a closed member back out of
  the figure, and let the tutor time a member's entry by when they marked
  completion.)
- **Eligible member:** a student with a counted session whose email was
  verified by `S` (`email_verified_at <= S`, the first verification; a later
  verification does not move it, so a student who first verifies after `S`
  never counts), whose account is at least 30 days old at `S`, who has not
  opted out, and who has **never blocked this tutor** (any `tutoring_blocks`
  row from the student to the tutor's user, active or removed; row 13).
  Verification after `S` is excluded because such a student would join with an
  early close instant and displace a published member, a one-member swap of
  the figure outside any step of k (T05 review).
- **Published set P:** eligible members with `now >= C`, ordered by
  `(C, opaque ref)`; P is the first `floor(n_closed / k) * k` of them, so the
  set only ever grows by k members at a time.
- **Eligible observation:** an attempt with `origin = 'past_paper'`,
  `deleted_at IS NULL`, `grade` on the ladder, `boundary_source = 'exact'`, and
  `subject_code` equal to the figure's subject (`is_outcome_eligible`, with a
  SQL mirror and a parity test). The SQL filters explicitly; it never relies
  on the ORM soft-delete loader criterion (`lemely/db/session.py:178-218`).
  Estimated-boundary grades are left out and the caption says so.
- **During grade:** the latest eligible observation recorded in the window.
  **Before grade:** the latest recorded in `[S − 180 days, S)`. `recorded_at`
  is the upload time, not the date the paper was sat; the caption says
  "papers uploaded in the 120 days from each student's first session".
- **Change:** ladder position of before vs during; higher / same / lower; only
  members with both grades (`n_paired`).
- **Ladder** is an argument (default `GRADE_ORDER`), so a 9–1 board brings its
  own ladder without changing the function.

### When a figure is shown (each figure separately)

A figure is **sufficient** only if all of these hold; otherwise it shows the
insufficient state and every count is `None` (including `nWithoutGrade`):

1. **k on contributors, not cohort size** (row 13, SC-13a): `n_graded ≥ 5`
   for the distribution, `n_paired ≥ 5` for the change.
2. **Never-granted rule** (row 13, SC-14 i): among the figure's contributors,
   the number who never held a grant to this tutor (no `tutor_data_grants`
   row for the pair, live or revoked) is 0 or at least 5.
3. **Homogeneity rule** (row 13, SC-14 ii): the largest bucket holds at most
   `n − 2`. (This closes the O-3 homogeneity case of rev 1.)
4. **Change hold** (SC-13d): no student with a counted session in this subject
   changed their counting choice (`outcome_pref_changed_at`) or blocked this
   tutor (`tutoring_blocks.created_at`) in the last 90 days. Opting out or
   blocking removes the student on the next read, but the figure stays hidden
   for 90 days, so the change itself does not show their bucket.

### What the tutor can and cannot do to the figure

- **Cannot:** move it by any action after a session has happened. Marking
  completed or no-show, blocking a student, declining, or letting a request
  expire changes neither membership nor any grade in the figure
  (`test_outcomes_marking_complete_no_show_or_tutor_block_changes_nothing`
  asserts a byte-identical `OutcomesDTO` from T8 and SP4).
- **Can:** decide, before a session, whether it happens (accept, decline,
  cancel at any time before the start; inside 24 h only with a reason the
  student and linked parents see, row 18). That fixes S and therefore C for a
  new member. A cancelled booking never enters the cohort, so a late cancel
  moves nothing that an earlier cancel would not
  (`test_late_cancel_leaves_outcomes_unchanged`).
- **Can:** predict every C (they know each member's first session) and read
  the figure just before and just after a step of k. **This cannot be removed
  without a snapshot or another delay mechanism, and the user chose live
  figures (row 13).** It is recorded as R5 below.

## Options Considered

| Option | Assessment |
|--------|------------|
| A. Ordered bar only, opt-in, default off (**recommended at row 8**) | Consent-based; no causal figure |
| B. Dumbbell only | Shows individuals |
| C. Pie | Wrong chart for ordinal data |
| D. **Ordered bar + change figure, default-on with opt-out (chosen by user, row 8)** | Most informative; weaker consent; causal reading risk |

Timing (row 13):

| Option | Assessment |
|--------|------------|
| Monthly as-of snapshot evaluated at read time; opt-outs applied at the next as-of date (**recommended**, ADVERSARIAL F1) | A click never moves the figure; a reader sees at most 12 versions a year; still not leak-free |
| **Live figures with window-close entry, steps of k, SC-14 suppression, 90-day hold, blocked students excluded (chosen by user, row 13)** | No stored state; figures change only at predictable close instants, in steps of k; differencing across a step remains possible (R5) |
| Drop the change figure | Smallest leak; contradicts row 8 |

Computation: per request, three statements (profile check; cohort; observations), no cache, no materialised table, no sweeper job.

## Accepted risks and the compensating controls in force

| # | Accepted risk (argued against) | Controls built |
|---|---|---|
| R1 | Minors are counted without consent (default-on, row 8) | Notice in three places; one-tap opt-out; aggregates only; logged-in, verified viewers only; all suppression rules above |
| R2 | The change figure implies the tutor caused it | Fixed wording; neutral colours with direction icons; caveat names selection; k on `n_paired`; no averages |
| R3 | Marking noise moves grades | Caveat; estimated-boundary grades left out; counts only |
| R4 | Re-identification at small n | k on contributors; never-granted rule; homogeneity rule; exact n hidden when insufficient; opaque refs in the core |
| R5 | **Differencing across a step (row 13; ADVERSARIAL F1, residual)** | Steps of k, window-close entry, the never-granted rule on the whole set, the 90-day hold. Not enough to stop the scenario below |
| R6 | A grant revoked before a member's window closed still counts as "granted" for rule 2, although the tutor may not have seen that member's during grade | Rule 2 counts any grant row; tightening it to "a grant live at or after C" is a later option. Low likelihood (needs a revoke inside the window plus the R5 conditions) |
| R7 | A sock-puppet with a known grade pads the cohort | Verified email, 30-day account age at S, real-time sessions, Gemini spend per graded paper |
| R8 | **The 90-day hold does not hide an opt-out for good** (T05 review, residual like R5). If no step of k happens in between, a reading taken before a student's opt-out change and one taken after the hold ends differ only by that student, so the difference still shows the student's bucket (and, in the change figure, their direction) | The hold stops a reading straight after the change; steps of k when they happen; the never-granted and homogeneity rules on the whole set. Not enough to stop the scenario |
| R9 | **Grades are not frozen at the close instant** (T05 review, residual). Deleting or restoring an attempt (`deletion_repo`), or a self-review or teacher regrade (`review_repo`), changes a published member's before or during grade after C, outside any hold, so readings before and after the change show that member's new bucket | Only exact-boundary past papers count; the never-granted and homogeneity rules on the whole set. Freezing grades at C would need stored state, which row 13 declined |

**R5, the exact scenario.** Tutor T has 5 published members in 0625, none of
whom ever granted access (rule 2: 5 ≥ k, so the figure is shown). Five more
members will close on 2026-06-30, because T accepted their first sessions on
dates that put each `S + 120 days` on or before that day. Four of them granted
T access; the fifth, X, never did. On 2026-06-29 T opens T8 and records the
distribution. On 2026-06-30 the published set grows from 5 to 10 (never-granted
count 6 ≥ 5, largest bucket ≤ n − 2, so the figure stays shown). T opens T8
again, subtracts the first figure, subtracts the four granted members' during
grades (read on T20), and is left with X's during grade. The change figure
gives X's higher/same/lower result the same way. T clicked nothing between the
two reads. Any logged-in account can do the same through SP4 if it knows the
members and their grades, which in practice only the tutor does. The
suppression rules apply to the whole published set, not to the members who
entered at the last step; testing the step itself would need either the
previous published set (a snapshot) or a rule that depends on the order of
past reads, and the user declined the snapshot.

**Ladder (former SPEC O-4, confirmed by decision-log row 19 on 2026-10-25):**
row 8 says "A*..G". Recorded grades stop at E and then U; F and G are not
grade-bearing today. The chart renders the recorded ladder, U included.

## Consequences

- Easier: one pure function, fully unit-testable; opt-out is one row; no job.
- Harder: three statements per profile view; a long "Results are hidden for
  now" period for every new tutor (at least 120 days after the fifth eligible
  student's first session), which the UI must present as normal.
- The figures exclude estimated-boundary grades, so a subject whose papers
  mostly lack exact boundaries may never become sufficient. That is the honest
  outcome.

## Action Items
1. [ ] `lemely/core/tutor_outcomes.py` + exhaustive unit tests (SPEC §e.4 Outcomes).
2. [ ] Outcome statements in `tutor_directory_repo.py` + one DB test per exclusion, each with a red case (SPEC §e.3).
3. [ ] `student_tutoring_preferences` (with `outcome_pref_changed_at`) in `0047`; `tutoring_blocks.removed_at` in `0050`.
4. [ ] C-17 and C-18 with table alternatives; S-34 caption and insufficient copy.
5. [ ] DELIVERY §5.7 carries R5 verbatim in plain words (SPEC §g).
