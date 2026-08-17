# Subject names as the primary identifier

Date: 2026-08-17

## Purpose

Across the web UI, a subject is currently identified first by its CAIE
syllabus code ("0625") with the human name a secondary or absent detail.
The product should lead with the readable name ("Physics") and treat the
code as secondary, supporting metadata — and, where a qualification level
is known for that subject, show it alongside the name (e.g. "Physics
IGCSE").

This touches three things that don't exist together anywhere today:

1. A reliable human name per subject, everywhere a subject is displayed.
2. A qualification level *per subject a student is enrolled in* — the only
   qualification-level field that exists today (`StudentProfile.qualification_level`)
   is one value for the whole student, which is wrong for a student who
   mixes levels across subjects (e.g. IGCSE Physics alongside O-Level
   Math).
3. Consistent primary/secondary display ordering across the student,
   parent, teacher and admin portals.

## Current state

- `lemely/io/det/profiles.py::SUBJECT_PROFILES` and
  `lemely/db/seed.py::DEMO_SUBJECTS` are the two places bare subject names
  ("Physics", "Mathematics", "Additional Mathematics") already live,
  keyed by CAIE code. Neither has an "O-Level"/"IGCSE" qualifier — that is
  a per-enrolment fact, not a property of the subject itself.
- `lemely/web/routers/parent.py::_subject_name(code)` already resolves a
  real name via `get_profile(code).name`, with a fallback to the raw
  code. Parent-portal screens (`ChildOverview.tsx`, `SubjectDetail.tsx`)
  are already name-primary/code-secondary as a result.
- `lemely/web/routers/student.py::_subjects()` (backs the student
  Overview) deliberately sets `SubjectRowDTO.name = code`, documented
  in its own docstring as intentional: "history records carry no human
  subject name... name echoes the code." The frontend
  (`Overview.tsx::SubjectLedgerRow`) treats the code as the row's
  identity as a direct consequence, with a comment explicitly saying the
  fix belongs server-side.
- The student sidebar (`SubjectNavGroup` in `portals/student/index.tsx`)
  is already name-primary, code-secondary (added in commit `b8c8282`) —
  no change needed there.
- Teacher (`Classes.tsx`, `ClassDetail.tsx`) and admin (`Classes.tsx`)
  screens show only the bare `subjectCode` on a `SchoolClass`, no name at
  all.
- `StudentProfile.qualification_level` (`lemely/db/models/profiles.py`,
  enum `igcse | o_level | as_level | a_level`) is set once during
  onboarding (S-02) and applies to the whole student. It is not attached
  to any individual subject enrolment.
- `student_subject_enrolments` (`lemely/db/models/profiles.py::StudentSubjectEnrolment`)
  is the per-(student, subject) row — target grade, session, papers — but
  has no level column today.
- The frontend already has a canonical enum → label table for the four
  qualification levels: `QUALIFICATION_LEVELS` in
  `web/src/portals/student/screens/onboarding/onboardingData.ts`.

## Decisions

These were confirmed with the product owner before writing this spec:

- **Scope**: apply name-primary display to all four portals (student,
  parent, teacher, admin).
- **Backend fix**: `student.py::_subjects()` must resolve real names via
  `get_profile()`, the same pattern `parent.py` already uses, rather than
  continuing to echo the code.
- **Level format**: the identifier includes a qualification-level
  qualifier (e.g. "Physics IGCSE"), not just the bare subject name.
- **Level granularity**: qualification level is **per subject
  enrolment**, not per student. This requires a new column on
  `student_subject_enrolments`; the existing profile-level field is not
  reused as the source of truth.
- **Profile-level field's role**: `StudentProfile.qualification_level`
  stays. It becomes the *default* that pre-fills a new enrolment's level
  in onboarding, not the thing displayed.
- **Backfill**: existing enrolment rows get their level copied from that
  student's profile-level value at migration time (`NULL` if the student
  never set one).
- **Teacher/admin scope**: `SchoolClass` rows show name + code only, no
  level qualifier. A class isn't one student's enrolment, so there is no
  single level to show without inventing a new `SchoolClass.qualification_level`
  field, which is out of scope here.

## Data model

Add a nullable column to `student_subject_enrolments`:

```
qualification_level  ENUM('igcse','o_level','as_level','a_level')  NULL
```

Reuses the existing `qualificationlevel` PG enum type created for
`student_profiles.qualification_level` (`lemely/db/migrations/versions/0009_student_profiles.py`)
— no new enum type.

Migration steps:
1. Add the column, nullable, no default.
2. Backfill: for every existing `student_subject_enrolments` row, set
   `qualification_level` to that row's `user_id`'s
   `student_profiles.qualification_level` (single `UPDATE ... FROM`
   join; rows whose student never set a profile-level value stay
   `NULL`).

No new enum type, no changes to `student_profiles` or `subjects`.

## Backend changes

**`lemely/db/models/profiles.py`**
- `StudentSubjectEnrolment`: add `qualification_level` column as above.

**`lemely/db/student_profile_repo.py`**
- `SubjectEnrolmentRow`: add `qualification_level: QualificationLevel | None`.
- `upsert_enrolment(...)`: add an optional `qualification_level` keyword
  (same `UNSET`/`None`/value pattern already used for `target_grade` /
  `session_month`). When **creating** a new enrolment and the caller
  passes `UNSET`, default it to the student's current
  `StudentProfile.qualification_level` (read via the same session,
  no extra round trip). Updating an existing enrolment with `UNSET`
  leaves its level untouched, matching every other field on this method.
- `list_enrolments`: include the new field in the returned rows (already
  a straight column read).

**`lemely/web/routers/student.py`**
- `_subjects(history: StudentHistory, enrolments: dict[str, SubjectEnrolmentRow])`:
  resolve `name` via `get_profile(code).name or code` (mirrors
  `parent.py::_subject_name`) instead of echoing `code`. Add
  `qualificationLevel` to `SubjectRowDTO`, sourced from the matching
  enrolment (`None` if the student has papers for a subject they never
  formally enrolled in — that's an existing possible state and gets no
  level, not an invented one).
- `student_overview(...)`: wire in `StudentProfileService` (already
  injectable via `get_student_profile_service`, just not used by this
  endpoint yet) to fetch `list_enrolments()` and pass the code→row map
  into `_subjects`.

**`lemely/web/schemas_student.py`**
- `SubjectRowDTO`: add `qualificationLevel: str | None`.

**`lemely/web/schemas_student_profile.py`** (or wherever the enrolment
request/response DTOs live)
- Add `qualificationLevel: str | None` to both the enrolment response DTO
  and the `PUT /me/enrolments` request payload per subject.

**`lemely/web/routers/me.py`**
- `_enrolment_to_dto`: map the new field through.
- `put_student_profile_enrolments`: pass `qualificationLevel` from the
  request into `upsert_enrolment(...)`.

**`lemely/web/routers/parent.py`**
- Child-subject DTOs gain `qualificationLevel`, sourced the same way
  (`list_enrolments` for that child).

All new fields are the **raw enum value** (`"o_level"`, not `"O-Level"`).
Formatting to a human label happens once, on the frontend, via the
existing `QUALIFICATION_LEVELS` table — no duplicate label table on the
backend.

## Frontend changes

**New shared helper**, next to `web/src/components/ui/subject-tag.tsx`
(exact placement decided during implementation — either a function in
that file or a small new `subject-label.ts`):

```ts
function subjectIdentifier(name: string, code: string, level: string | null): {
  primary: string        // "Physics"
  secondary: string       // "IGCSE · 0625" or just "0625" if level is null
}
```

Every screen that shows a subject switches to rendering `primary` as the
prominent text and `secondary` as the smaller/muted supporting text,
replacing whatever ad hoc code-first rendering it has today. No call site
invents its own name or level string.

**Files to update:**
- `portals/student/screens/Overview.tsx::SubjectLedgerRow` — flip the
  code chip and the name span's roles; the `row.name !== row.code` guard
  goes away entirely once the backend always supplies a real name.
- `portals/student/screens/Subject.tsx` — page heading and any
  code-first copy.
- `portals/student/data.ts::resolveCrumb` / `resolveCrumbTrail` — the
  subject breadcrumb arm currently interpolates the raw code
  (`` `Home / ${subjectMatch[1]}` ``); decide during implementation
  whether to fetch the name for the crumb or leave the crumb
  code-only (crumbs are deliberately id-free elsewhere in this file for
  routes with no cheap name available — the existing "This result" precedent
  applies if fetching a name here isn't cheap).
- `portals/student/index.tsx::SubjectNavGroup` — no structural change
  (already name-primary); switch its `tag` to use the new helper's
  `secondary` so level shows there too.
- `portals/parent/screens/ChildOverview.tsx`, `SubjectDetail.tsx` —
  already name-primary; add the level into the existing secondary line.
- `portals/teacher/screens/Classes.tsx`, `ClassDetail.tsx`,
  `portals/admin/screens/Classes.tsx` — currently code-only; switch to
  name-primary/code-secondary (via `get_profile`-backed name from
  whatever `SchoolClass` DTO already carries or a new lookup — no level).
- `portals/student/screens/onboarding/SubjectsStep.tsx` — the
  qualification-level selector stays as the step's opening control
  (still sets the default passed to new enrolments); each subject card
  gains a small per-subject level control, pre-filled from that default,
  which the student can override before submitting.
- `lib/studentTypes.ts::SubjectRow`, `lib/meTypes.ts::SubjectEnrolment`,
  parent-side subject types — add `qualificationLevel: string | null`.

## Testing

- **Migration**: a test asserting the new column exists, is nullable,
  and that the backfill copies the profile-level value onto pre-existing
  enrolment rows (and leaves it `NULL` where the profile had none).
- **Repo**: `upsert_enrolment` test — creating a new enrolment with no
  explicit level defaults to the profile's level; updating an existing
  enrolment with `UNSET` leaves its level untouched; explicit `None`
  clears it.
- **Router**: `student_overview` returns a real `name` (not the code) and
  the correct `qualificationLevel` per subject; `PUT /me/enrolments`
  round-trips a per-subject level; parent child-overview includes it.
- **Frontend unit**: the `subjectIdentifier` helper — level present,
  level `null`, name missing (should not happen post-fix, but the helper
  should not crash).
- Existing tests asserting `SubjectRowDTO.name == code` (a consequence of
  the current deliberate behaviour) need updating to reflect the new,
  correct behaviour.

## Out of scope

- A `SchoolClass`-level qualification field (teacher/admin classes show
  name + code only, no level).
- Any change to `StudentProfile.qualification_level`'s own storage or
  the onboarding step-1 UI beyond adding the per-subject override.
- Backfilling or inventing names/levels for subjects outside the three
  the build currently supports (`DEMO_SUBJECTS`).
