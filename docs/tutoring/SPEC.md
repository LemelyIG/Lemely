# Tutoring marketplace — specification

**Status:** Rev 3: open user decisions D-1, D-2 and the reading calls resolved (decision-log rows 17–19) · **Date:** 2026-10-25 · **Branch:** `feat/tutoring-marketplace` (off `develop` @ `314ef8ec`; `origin/develop` is 117 commits ahead and is **merged** into the branch before wave 1 with one signed merge commit, never rebased, because the branch is already on origin; §f)
**Amended 2026-10-25 by PLAN rev 2** (`docs/tutoring/ADVERSARIAL-PLAN.md` P4, P5, P8, P12): §a.1 preference mirrors and their role table, §b.2 legend and §b.5 `no-store` scope, §c.1 and §f merge wording, §f PR shape. Each change is mapped in `docs/tutoring/PLAN-REVISION-LOG.md`; no locked decision row changes.
**Locked inputs (not changed here):** `BUILD/tutoring/decision-log.md` rows 0–19 (all LOCKED; rows 13–16 are the spec-review decisions, rows 17–19 the rev 3 decisions), `BUILD/tutoring/design-summary.md`, `BUILD/tutoring/recon.md`.
**Implementation plan:** `BUILD/tutoring/PLAN.md` (tasks, execution waves, file ownership, the single PR and its CI cadence). Build order follows its waves; the migration revisions and their contents in §f are unchanged.
**Decisions:** `docs/tutoring/adr/ADR-T01..T04`, `BUILD/DECISIONS.md` entries `D-2026-10-25 — tutoring: *`.
**Review inputs resolved here:** `docs/tutoring/THREAT-MODEL.md` (SC-1..SC-27), `docs/tutoring/ADVERSARIAL-SPEC.md` (F1..F36). Every item is mapped in `docs/tutoring/REVISION-LOG.md`.

Every symbol cited below was checked by a direct read of this worktree at
`314ef8ec`, either in this revision or by the two reviews (which read the same
tree). New IDs were checked for collisions: components end at C-16
(`docs/COMPONENT_CATALOGUE.md`), screens as stated in §d. Things that could
not be checked are in §h.

---

## 0. Conventions used throughout

| Topic | Rule |
|---|---|
| Layering | Pure logic in `lemely/core/*` (no `lemely.db`, `lemely.web`, `sqlalchemy`, `fastapi`); SQL in `lemely/db/*_repo.py`; HTTP in `lemely/web/routers/*` + `schemas_*.py`. `lemely/io/notify_email.py` for the transactional email provider seam. |
| Times | API carries ISO-8601 instants with offset, stored as `timestamptz` (UTC). Weekly availability is wall-clock in the tutor's zone (`tutor_profiles.zone`, default `Africa/Cairo`). Tutoring screens render session times in the tutor's zone with its label ("Cairo time"), for every viewer, because a session (often in person) happens in the tutor's locality; this differs on purpose from the rest of the product, which renders in `users.timezone`. |
| Clock | Every compare-and-set and every time guard inside a write transaction uses the database `now()`, never the app clock (BK-7). Reads use the app clock for display only. |
| IDs | UUID v4 (`gen_random_uuid()`) everywhere, including log tables (no global identity counter is ever exposed; ID-5). |
| DTO style | `ApiModel` (`lemely/web/schemas.py:35`): `extra="forbid"`, camelCase fields. Query params camelCase (precedent: `unreadOnly`). |
| Errors | FastAPI `HTTPException`. Validation 422 (FastAPI default). State and policy conflicts 409 with `detail={"code": "<code>", "message": "<plain English>"}`. Unverified email: **403** `{"code":"email_unverified"}` via the existing `require_verified_email` dependency (`lemely/web/deps.py:966-1010`). Quotas: 429 `{"code":"too_many_requests"}`. Object not visible to the caller: 404 unless stated (no existence oracle), except the parent child-link rule, which keeps the existing parent routes' 403/404 split (precedent documented at `teacher.py:2406-2414`). |
| Paging | Keyset on every list: `?cursor=<opaque>&limit=<1..50, default 20>`; response `{items: [...], nextCursor: str \| null}`. Cursor = base64url JSON `{"e": <endpoint tag>, "k": [<sort-key values>]}` (`lemely/core/keyset.py`). Decoding is typed per endpoint (UUID, Decimal, ISO instant); a cursor with the wrong tag, arity or types → 422 (O21). Values are only ever bound as SQL parameters. |
| Process state | None. No in-memory caches, limiters or queues. The only timed work this feature adds is one job on the existing 60-second sweeper (§b.4); every state (expiry, staleness, outcome membership) is evaluated at read time. |
| Free text | Every user-written tutoring field passes `lemely.core.contact_patterns` (SC-7) and is rendered as plain text, never auto-linked. |
| Display names | A student's name shown to a tutor is `core.tutor_directory.student_label(display_name, user_id)`: the trimmed `users.display_name`, or "Student " + the first 4 hex characters of `sha256(user_id)` uppercased. **Never** the `display_name or email` fallback used by `class_repo.py`/`parent_repo.py` (F12). |
| Copy | English; must pass `web/scripts/check_copy.mjs` (no prose em dashes, no exclamation marks). Never "improvement"; never "verified" without "documents seen". A new copy-lint rule bans both words in tutoring copy (§d). |
| Prices | None anywhere. Profile and booking screens say "Fees are agreed between you and the tutor, outside Lemely." |

---

## a. Data model

All tables are new except additive changes to existing types and tables
(`notificationtype` values, `notification_preferences` columns). Every table
has `created_at`/`updated_at` `timestamptz NOT NULL DEFAULT now()` via
`TimestampMixin` unless stated. Constraint names follow `NAMING_CONVENTION`
(`lemely/db/base.py:16`). **The convention prefixes `ck_%(table_name)s_`
itself, so code passes the short name** (`name="first_name_len"`), never the
full name printed below (trap recorded in migration 0034, F34). Exclusion
constraints, which the convention does not cover, are named
`excl_<table>_<what>` explicitly. **PII** marks a privacy-sensitive column;
**PUBLIC** marks a column served without login.

**Deletion rule (SC-21, F18).** No account-deletion path exists in `lemely/`
today, but tests hard-delete users (`tests/test_notification_repo.py:585`), so
ON DELETE rules are live. Safeguarding records never cascade away: a user who
owns a tutor profile or is the subject of a booking cannot be deleted
(`RESTRICT`) until an offboarding procedure anonymises them (out of scope;
§i.3 O-12). Tutor profiles are never deleted; they are **closed** (A12).

### a.1 Enum types (all new, created in `0044`)

| Postgres type | Values | Python enum (`lemely/db/models/enums.py`) |
|---|---|---|
| `tutorlistingstate` | `draft`, `pending_review`, `listed`, `rejected`, `suspended`, `closed` | `TutorListingState` |
| `tutoringmode` | `virtual`, `in_person`, `other` | `TutoringMode` |
| `bookingstate` | `requested`, `accepted`, `declined`, `cancelled`, `completed`, `no_show`, `expired` | `BookingState` |
| `bookingparty` | `student`, `parent`, `tutor`, `platform_admin`, `system` | `BookingParty` |
| `moderationstate` | `none`, `pending`, `approved`, `rejected` | `ModerationState` |
| `tutorgrantscope` | `all_subjects_derived` | `TutorGrantScope` |
| `grantrevokereason` | `student`, `block`, `tutor_suspended`, `tutor_closed` | `GrantRevokeReason` |
| `tutoraccessaction` | `list`, `detail` | `TutorAccessAction` |
| `tutorapprovaldecision` | `approved`, `rejected`, `suspended`, `reinstated`, `closed` | `TutorApprovalDecision` |
| `reporttargettype` | `tutor_profile`, `review`, `review_reply`, `booking`, `booking_note` | `ReportTargetType` |
| `reportreason` | `safety_concern`, `inappropriate_content`, `harassment`, `spam`, `fake_profile`, `disputed_outcome`, `other` | `ReportReason` |
| `reportstate` | `open`, `dismissed`, `actioned` | `ReportState` |
| `reportresolution` | `dismissed`, `content_hidden`, `tutor_suspended`, `booking_cancelled`, `booking_completed` | `ReportResolution` |
| `emailoutboxstatus` | `pending`, `sent`, `failed`, `skipped` | `EmailOutboxStatus` |
| `parentlinkevent` | `linked`, `unlinked` | `ParentLinkEvent` |
| `tutoringadminaction` | `report_thread_view`, `evidence_open` | `TutoringAdminAction` |

**Additive values on an existing type** (`ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS`, precedent `0039_paper_soft_delete`), 8 values:
`booking_request`, `booking_update`, `booking_note`, `tutor_access`, `tutor_review`, `tutor_listing`, `parent_link` (SC-1), `tutoring_report` (SC-10).

**Additive columns on an existing table** (`notification_preferences`), one per new type, each `boolean NOT NULL DEFAULT true`, because `test_notification_type_enum_matches_preference_columns` (`tests/test_db_schema.py:182`) pins enum values to preference columns.
Mirrors to update in the same wave: `NotificationPreferencesDTO` (`lemely/web/schemas_me.py:18`), `NotificationPreferencesUpdateDTO` (`schemas_me.py:85`), `web/src/lib/notificationTypes.ts`, `web/src/lib/notificationPrefs.ts`, `web/src/lib/staffInbox.ts` (F32). **Added by PLAN rev 2 (P4):** `lemely/db/notification_prefs_repo.py` (the preferences dataclass, `set` keyword arguments, merge and model mapping; `tests/test_notification_repo.py` pins every mapped field to `DEFAULTS`), `lemely/web/routers/me.py` (`_to_dto` and the PUT role checks) and `web/src/portals/settings/NotificationSettings.tsx` (a tutoring toggle renders only when its GET value is non-null).

Role gating of the 8 toggles follows the existing `atRiskAlert`/`reviewWithdrawn` pattern (`me.py:102-111`: null on GET for any other role, 422 on a PUT that supplies the field from any other role). The allowed roles are exactly the roles §b.4 sends that type to; no new product decision is made here.

| Type | Allowed roles (GET non-null, PUT accepted) | §b.4 recipients it is derived from |
|---|---|---|
| `booking_request` | teacher | tutor |
| `booking_update` | student, parent, teacher | student, linked parents, tutor (other party on cancel; on student or parent completion) |
| `booking_note` | student, parent, teacher | the other participant; linked parents (tutor-authored, daily) |
| `tutor_access` | student, parent, teacher | tutor, linked parents, student (grant ended by suspension or close) |
| `tutor_review` | student, teacher | author student, tutor (reply moderated) |
| `tutor_listing` | teacher | tutor |
| `parent_link` | parent | parents |
| `tutoring_report` | platform_admin | every `platform_admin` |

`school_admin` gets none of the 8. Gating is by role, not by owning a tutor profile, so a teacher without a profile sees the teacher toggles (a teacher may create a profile at any time).

Core-side `Literal` vocabularies that mirror `bookingstate`/`bookingparty` are
pinned equal to the Python enums by a test (precedent: `PaperOrigin` ↔
`AttemptOrigin`, `lemely/core/history.py:33`).

### a.2 Tables

#### `tutor_profiles` (0045)
| Column | Type | Null / default | Constraint / note |
|---|---|---|---|
| `id` | uuid | PK | `pk_tutor_profiles` |
| `user_id` | uuid | NOT NULL | FK `users.id` **ON DELETE RESTRICT**; `uq_tutor_profiles_user_id`. Service checks `users.role = teacher` at create. |
| `public_first_name` | varchar(40) | NOT NULL | **PUBLIC, PII**. `ck_tutor_profiles_first_name_len`: `char_length(btrim(public_first_name)) BETWEEN 1 AND 40`. `ck_tutor_profiles_first_name_chars`: `public_first_name !~ '[0-9./@:]' AND public_first_name !~ '[[:cntrl:]]'`. The service enforces the full allowlist (SC-25): Unicode letters (Arabic included), space, hyphen, apostrophe; no bidi controls U+202A–202E, U+2066–2069 (`core.tutor_directory.validate_public_name`) |
| `public_last_initial` | varchar(1) | NULL | **PUBLIC, PII**. NULL or one character: `ck_..._last_initial_len`: `char_length(public_last_initial) = 1` (NULL passes); the service requires `str.isalpha()` |
| `headline` | varchar(160) | NOT NULL | **PUBLIC** ("short bio" on the card). `ck_..._headline_not_blank`: `char_length(btrim(headline)) >= 1` |
| `bio` | text | NOT NULL DEFAULT `''` | logged-in only. `ck_..._bio_len`: `char_length(bio) <= 2000` |
| `qualification_note` | text | NULL | logged-in only. `ck_..._qualification_note_len`: `char_length(qualification_note) <= 1000` |
| `offers_virtual`, `offers_in_person`, `offers_other` | boolean | NOT NULL DEFAULT false | **PUBLIC**. `ck_..._has_mode`: at least one true |
| `other_mode_note` | varchar(200) | NULL | logged-in only, **moderated** (F14). `ck_..._other_note`: `offers_other OR other_mode_note IS NULL` |
| `country_code` | char(2) | NOT NULL DEFAULT `'EG'` | |
| `area_code` | varchar(40) | NOT NULL | **PUBLIC**, city level. Validated against `lemely/data/tutoring_areas.json` (`code`, `name`, `country_code`), never free text; served by P3 |
| `zone` | varchar(64) | NOT NULL DEFAULT `'Africa/Cairo'` | IANA zone for availability rules and time labels. Not settable in v1 (no DTO field); it exists so a second country needs no table change (F27) |
| `listing_state` | tutorlistingstate | NOT NULL DEFAULT `'draft'` | §a.3 |
| `submitted_at` | timestamptz | NULL | last submit for review |
| `listed_at` | timestamptz | NULL | last approval |
| `first_listed_at` | timestamptz | NULL | first approval, never reset; feeds "Listed since" and the rank tie-break (F10) |
| `paused_at` | timestamptz | NULL | tutor-controlled; listed AND paused = hidden, bookings and new grants closed |
| `closed_at` | timestamptz | NULL | set with `listing_state = 'closed'` (A12). `ck_..._closed`: `(listing_state = 'closed') = (closed_at IS NOT NULL)` |
| `indexable` | boolean | NOT NULL DEFAULT true | **PUBLIC** (P2 only). Search engines may index this tutor's public card while true (row 17: indexable by default); the tutor opts out on T-16 through T3. Not a moderated field: changing it never sends the profile back to review. Read by the edge worker through P2 (§b.5) |
| `documents_seen_at` | timestamptz | NULL | set by an approval with `documentsSeen=true`; **cleared** by any evidence upload or delete and by any approval with `documentsSeen=false` (F14). "Documents seen" means only this |
| `rating_count` | integer | NOT NULL DEFAULT 0 | **distinct students** with a counted review (SC-16). `ck_..._rating_count_nonneg`: `rating_count >= 0` |
| `rating_sum` | integer | NOT NULL DEFAULT 0 | sum of each counted student's latest stars. `ck_..._rating_sum_range`: `rating_sum BETWEEN rating_count AND 5 * rating_count` |
| `rating_avg` | numeric(3,2) | GENERATED ALWAYS AS (`CASE WHEN rating_count = 0 THEN NULL ELSE round(rating_sum::numeric / rating_count, 2) END`) STORED | filter column |
| `rank_score` | numeric(7,6) | NOT NULL DEFAULT 4.000000 | written by the service from `core.tutor_ratings.bayesian_score` in the same transaction as any rating change; the default equals the score of zero reviews (prior mean) |

Indexes (listed-and-not-paused = `listing_state = 'listed' AND paused_at IS NULL`):
- `ix_tutor_profiles_directory` on `(rank_score DESC, first_listed_at, id)` WHERE listed-and-not-paused — default sort + keyset.
- `ix_tutor_profiles_area_rank` on `(area_code, rank_score DESC, first_listed_at, id)` WHERE listed-and-not-paused.
- `ix_tutor_profiles_rated` on `(rating_avg)` WHERE listed-and-not-paused AND `rating_count >= 3` — the `minRating` filter (F25).
- `ix_tutor_profiles_mode_virtual`, `_mode_in_person`, `_mode_other` on `(rank_score DESC, first_listed_at, id)` WHERE listed-and-not-paused AND `offers_<mode>`.
- `ix_tutor_profiles_review_queue` on `(listing_state, submitted_at, id)` — admin queue.

#### `tutor_subjects` (0045)
| Column | Type | Constraint |
|---|---|---|
| `tutor_profile_id` | uuid NOT NULL | FK `tutor_profiles.id` ON DELETE CASCADE (profiles are never deleted; the rule only matters to tests) |
| `subject_code` | varchar NOT NULL | FK `subjects.code` ON DELETE RESTRICT |
| PK | | `pk_tutor_subjects (tutor_profile_id, subject_code)` |

Index `ix_tutor_subjects_subject_code` on `(subject_code, tutor_profile_id)`. No timestamps. Max 10 per tutor (service).

#### `tutor_availability_rules` (0045) — weekly, wall-clock in `tutor_profiles.zone`
| Column | Type | Constraint |
|---|---|---|
| `id` | uuid PK | |
| `tutor_profile_id` | uuid NOT NULL | FK CASCADE |
| `iso_weekday` | smallint NOT NULL | `ck_..._iso_weekday_range`: `BETWEEN 1 AND 7` (Monday = 1) |
| `start_minute` | smallint NOT NULL | `ck_..._start_minute_range`: `BETWEEN 0 AND 1425 AND start_minute % 15 = 0` |
| `end_minute` | smallint NOT NULL | `ck_..._end_minute_range`: `BETWEEN 15 AND 1440 AND end_minute % 15 = 0 AND end_minute > start_minute` |
| exclusion | | `excl_tutor_availability_rules_no_overlap` (§a.4) |

Index `ix_tutor_availability_rules_window` on `(iso_weekday, start_minute, end_minute, tutor_profile_id)`. The exclusion's GiST index (leading `tutor_profile_id`) serves per-tutor reads and the FK. Max 42 rules per tutor. A window crossing midnight is two rules.

#### `tutor_evidence_files` (0045)
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | |
| `tutor_profile_id` | uuid NOT NULL | FK CASCADE; index `ix_tutor_evidence_files_tutor_profile_id` |
| `storage_path` | varchar(300) NOT NULL | **PII**. `tutor-evidence/{tutor_profile_id}/{uuid}.{ext}` in private bucket `settings.storage.tutor_evidence_bucket` (new). **A path, never a URL** (precedent `users.avatar_path`) |
| `original_filename` | varchar(200) NOT NULL | **PII**, sanitised |
| `content_type` | varchar(100) NOT NULL | `ck_..._content_type_allowed`: `IN ('application/pdf','image/jpeg','image/png')`, **set from sniffed magic bytes, never from the declared type** (SC-22) |
| `size_bytes` | integer NOT NULL | `ck_..._size_bytes_range`: `BETWEEN 1 AND 10485760` |
| `description` | varchar(200) NULL | passes SC-7 |

Max 5 per tutor. Images are re-encoded with Pillow (a runtime dependency, `pyproject.toml:22`) before storage, which drops EXIF and other metadata. Deleting a row deletes the object after commit (best effort; an orphan is logged with its path).

#### `tutor_approval_events` (0045) — append-only admin record
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | |
| `tutor_profile_id` | uuid NOT NULL | FK CASCADE |
| `admin_user_id` | uuid NULL | FK `users.id` SET NULL; index `ix_tutor_approval_events_admin_user_id` |
| `decision` | tutorapprovaldecision NOT NULL | |
| `documents_seen` | boolean NOT NULL DEFAULT false | |
| `note` | text NULL | admin-internal except rejection/suspension note, shown to the tutor. `ck_..._note_len`: `char_length(note) <= 2000` |
| `profile_snapshot` | jsonb NOT NULL | public + logged-in fields as decided |
| `created_at` | timestamptz NOT NULL DEFAULT now() | no `updated_at` |

Index `ix_tutor_approval_events_tutor` on `(tutor_profile_id, created_at DESC)`.

#### `tutoring_admin_access` (0045) — append-only platform-admin read log (SC-23)
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | |
| `admin_user_id` | uuid NULL | FK `users.id` SET NULL; partial index `ix_tutoring_admin_access_admin_user_id` WHERE `admin_user_id IS NOT NULL`, so deleting a user never scans the log |
| `action` | tutoringadminaction NOT NULL | `report_thread_view` (A10 on a booking/note target), `evidence_open` (A2 issuing a signed URL) |
| `tutor_profile_id`, `report_id`, `booking_id`, `evidence_id` | uuid NULL each | plain columns, **no FK**: a log row outlives its targets |
| `created_at` | timestamptz NOT NULL DEFAULT now() | no `updated_at`; no UPDATE/DELETE path in code |

Index `ix_tutoring_admin_access_tutor` on `(tutor_profile_id, created_at)`. Written in the same transaction that loads the thread or signs the URL; a failed insert fails the request (same fail-closed rule as `tutor_access_audit`).

#### `parent_link_events` (0046) — append-only parent-link history (SC-1, row 14)
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | |
| `child_id` | uuid NOT NULL | FK `users.id` ON DELETE CASCADE |
| `parent_id` | uuid NOT NULL | FK `users.id` ON DELETE CASCADE |
| `event` | parentlinkevent NOT NULL | |
| `created_at` | timestamptz NOT NULL DEFAULT now() | no `updated_at` |

Indexes `ix_parent_link_events_child` on `(child_id, created_at DESC)` and `ix_parent_link_events_parent_id` on `(parent_id)`. CASCADE (not RESTRICT) because this table records every parent link in the product, not only tutoring ones, and RESTRICT would change deletion behaviour for non-tutoring users.

#### `email_outbox` (0046) — generic transactional email
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | |
| `recipient_user_id` | uuid NOT NULL | FK `users.id` **ON DELETE CASCADE**; index `ix_email_outbox_recipient_user_id`. The address is resolved from `users.email` **at send time**; the outbox never stores an address (F18, EM-5) |
| `template` | varchar(60) NOT NULL | one of §b.4's templates |
| `context` | jsonb NOT NULL | validated against the template's typed schema (extra keys rejected, SC-25): ids, tutor public name, subject name, start instant, mode, event. **Never** note text, meeting link, location, an email address |
| `dedupe_key` | varchar(200) NOT NULL | `uq_email_outbox_dedupe_key`. Inserted with `ON CONFLICT (dedupe_key) DO NOTHING`, so a duplicate never aborts the business transaction (F17) |
| `status` | emailoutboxstatus NOT NULL DEFAULT `'pending'` | |
| `attempts` | smallint NOT NULL DEFAULT 0 | number of **send attempts**: 1 for `sent` and `failed`, 0 for `pending` and `skipped` (a row that was never handed to the provider was not attempted); never more than 1 in v1 (no retry, row 12) |
| `last_error` | varchar(500) NULL | provider status code + message with any address removed; `invalid_context` when the stored context no longer validates; for `skipped`, the reason (`mock_provider`, `unverified_recipient`, `placeholder_address`, `preference_off`, `daily_cap`, `recipient_missing`) |
| `sent_at` | timestamptz NULL | |

Indexes: `ix_email_outbox_pending` on `(created_at, id)` WHERE `status = 'pending'`; `ix_email_outbox_sent_at` on `(sent_at)` WHERE `status = 'sent'` (daily cap count).

#### `student_tutoring_preferences` (0047)
| Column | Type | Constraint |
|---|---|---|
| `user_id` | uuid PK | FK `users.id` CASCADE |
| `outcome_stats_opt_out` | boolean NOT NULL DEFAULT false | absent row = counted (row 8 default-on) |
| `outcome_pref_changed_at` | timestamptz NULL | set whenever `outcome_stats_opt_out` changes value; drives the 90-day hold (SC-13d) |
| `safety_notice_acknowledged_at` | timestamptz NULL | set once by S15; gates a student's first booking request and first note (row 16 ii) |
| `created_at`, `updated_at` | timestamptz | |

Index `ix_student_tutoring_preferences_opt_out` on `(user_id)` WHERE `outcome_stats_opt_out`.

#### `tutor_bookings` (0047)
| Column | Type | Null / default | Constraint / note |
|---|---|---|---|
| `id` | uuid | PK | plus `uq_tutor_bookings_id_tutor (id, tutor_profile_id)` and `uq_tutor_bookings_id_student (id, student_id)` as composite-FK targets (F34) |
| `tutor_profile_id` | uuid | NOT NULL | FK **RESTRICT** |
| `student_id` | uuid | NOT NULL | FK `users.id` **RESTRICT**. The **subject** of the booking (role student, checked by service) |
| `requested_by_user_id` | uuid | NULL | FK `users.id` SET NULL. The **actor** (student or parent) |
| `requested_by_party` | bookingparty | NOT NULL | `ck_..._requested_by_party_allowed`: `IN ('student','parent')` |
| `subject_code` | varchar | NOT NULL | FK `subjects.code` RESTRICT; one of the tutor's subjects (service) |
| `mode` | tutoringmode | NOT NULL | offered by the tutor (service) |
| `starts_at` | timestamptz | NOT NULL | must equal an instant produced by `core.booking.bookable_slots` for this tutor (BK-7) |
| `ends_at` | timestamptz | NOT NULL | `ck_..._duration`, one CHECK holding both conditions: `ends_at > starts_at`; `ends_at - starts_at BETWEEN interval '30 minutes' AND interval '4 hours'` |
| `slot` | tstzrange | GENERATED ALWAYS AS (`tstzrange(starts_at, ends_at, '[)')`) STORED | exclusion constraints and overlap reads only |
| `state` | bookingstate | NOT NULL DEFAULT `'requested'` | §a.3 |
| `meeting_link` | varchar(500) | NULL | **sensitive**. Set at accept for virtual; host allowlist (SC-7); served after accept to participants and linked parents. `ck_..._meeting_link_mode`: `meeting_link IS NULL OR mode = 'virtual'` |
| `location_detail` | varchar(300) | NULL | **PII**. Exact meeting place, set at accept for in-person; passes SC-7. `ck_..._location_detail_mode`: `location_detail IS NULL OR mode = 'in_person'` |
| `other_mode_note` | varchar(300) | NULL | passes SC-7. `ck_..._other_mode_note_mode`: `other_mode_note IS NULL OR mode = 'other'` |
| `decline_reason`, `cancel_reason` | varchar(300) | NULL | free text, pass SC-7, reportable. System reasons are fixed literals stored as written; tutor-facing DTOs show system cancellations as "Cancelled" (SC-11) |
| `cancelled_by_party` | bookingparty | NULL | |
| `cancelled_by_user_id` | uuid | NULL | FK SET NULL |
| `completed_by_party` | bookingparty | NULL | who recorded `completed`: `tutor`, `student`, `parent`, `platform_admin` (SC-17). No CHECK limits this value: only the service guards which party may record an outcome (`completed_ts` below only requires it to be set) |
| `notes_frozen_at` | timestamptz | NULL | set by a `safety_concern` report from a party (SC-10), cleared at report resolution |
| `accepted_at`, `declined_at`, `cancelled_at`, `completed_at`, `no_show_marked_at`, `expired_at` | timestamptz | NULL | coherence checks below |

Coherence CHECKs (`ck_tutor_bookings_*`):
- `accepted_ts`: `state NOT IN ('accepted','completed','no_show') OR accepted_at IS NOT NULL`
- `declined_ts`: `state <> 'declined' OR declined_at IS NOT NULL`
- `cancelled_ts`: `state <> 'cancelled' OR (cancelled_at IS NOT NULL AND cancelled_by_party IS NOT NULL)`
- `completed_ts`: `state <> 'completed' OR (completed_at IS NOT NULL AND completed_by_party IS NOT NULL)`
- `no_show_ts`: `state <> 'no_show' OR no_show_marked_at IS NOT NULL`
- `expired_ts`: `state <> 'expired' OR expired_at IS NOT NULL`
- `virtual_link`: `state NOT IN ('accepted','completed','no_show') OR mode <> 'virtual' OR meeting_link IS NOT NULL`
- `in_person_location`: `state NOT IN ('accepted','completed','no_show') OR mode <> 'in_person' OR location_detail IS NOT NULL`
- `late_cancel_reason` (row 18): `state <> 'cancelled' OR cancelled_by_party <> 'tutor' OR cancelled_at <= starts_at - interval '24 hours' OR (cancel_reason IS NOT NULL AND char_length(btrim(cancel_reason)) >= 1)`. The `IS NOT NULL` conjunct is required: without it a NULL reason makes the expression NULL and the CHECK passes. The literal `24 hours` is pinned to `core.booking.CANCEL_CUTOFF` by a test against the migration text and the ORM text

Exclusion and uniqueness (§a.4): `excl_tutor_bookings_tutor_slot`, `excl_tutor_bookings_student_slot` (approved, row 15c), `uq_tutor_bookings_one_pending`.

Indexes:
- `ix_tutor_bookings_tutor_starts` on `(tutor_profile_id, starts_at, id)`.
- `ix_tutor_bookings_student_starts` on `(student_id, starts_at, id)`.
- `ix_tutor_bookings_tutor_requests` on `(tutor_profile_id, starts_at)` WHERE `state = 'requested'` (the read filters `starts_at > now()` on top, F6).
- `ix_tutor_bookings_outcome_cohort` on `(tutor_profile_id, subject_code, student_id, starts_at)` WHERE `accepted_at IS NOT NULL AND state IN ('accepted','completed','no_show')` — outcome membership (ADR-T04).
- `ix_tutor_bookings_requested_by` on `(requested_by_user_id, created_at)` WHERE NOT NULL — FK, parent cancel, create quota.
- `ix_tutor_bookings_cancelled_by` on `(cancelled_by_user_id, cancelled_at)` WHERE NOT NULL — FK, cancel quota.

#### `tutor_booking_notes` (0047)
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | |
| `booking_id` | uuid NOT NULL | FK `tutor_bookings.id` **RESTRICT** |
| `author_user_id` | uuid NULL | FK SET NULL; partial index `ix_tutor_booking_notes_author_user_id` |
| `author_party` | bookingparty NOT NULL | `ck_..._author_party_allowed`: `IN ('student','tutor')`. Parents never write notes; a parent's `firstNote` is refused with 422 (F19, SC-24) |
| `body` | text NOT NULL | **PII, safeguarding**. `ck_..._body_len`: `char_length(btrim(body)) BETWEEN 1 AND 2000`; passes SC-7. Immutable |
| `hidden_at` | timestamptz NULL | set by an admin via report resolution |
| `hidden_by_user_id` | uuid NULL | FK SET NULL; partial index `ix_tutor_booking_notes_hidden_by_user_id` (F34) |

Index `ix_tutor_booking_notes_thread` on `(booking_id, created_at, id)`.

#### `tutor_reviews` (0048)
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | plus `uq_tutor_reviews_id_tutor (id, tutor_profile_id)` |
| `booking_id` | uuid NOT NULL | FK RESTRICT; `uq_tutor_reviews_booking_id` — **one review per booking** |
| `tutor_profile_id` | uuid NOT NULL | composite FK `fk_tutor_reviews_booking_tutor_tutor_bookings`: `(booking_id, tutor_profile_id) → tutor_bookings(id, tutor_profile_id)` (F34) |
| `student_id` | uuid NOT NULL | composite FK `fk_tutor_reviews_booking_student_tutor_bookings`: `(booking_id, student_id) → tutor_bookings(id, student_id)`; FK `users.id` RESTRICT; index `ix_tutor_reviews_student_id` |
| `stars` | smallint NOT NULL | `ck_..._stars_range`: `BETWEEN 1 AND 5` |
| `body` | text NULL | `ck_..._body_len`: `char_length(body) <= 1000`; moderated; passes SC-7 |
| `text_state` | moderationstate NOT NULL | `ck_..._text_state_matches_body`: `(body IS NULL) = (text_state = 'none')` |
| `text_moderated_at` | timestamptz NULL | |
| `text_moderated_by` | uuid NULL | FK SET NULL; partial index `ix_tutor_reviews_text_moderated_by` (F34) |
| `removed_at` | timestamptz NULL | admin removal (excluded from aggregates and lists) |

Indexes: `ix_tutor_reviews_listing` on `(tutor_profile_id, created_at DESC, id DESC)` WHERE `removed_at IS NULL`; `ix_tutor_reviews_pending` on `(created_at, id)` WHERE `text_state = 'pending' AND removed_at IS NULL`; `ix_tutor_reviews_student_latest` on `(tutor_profile_id, student_id, created_at DESC)` WHERE `removed_at IS NULL` (SC-16 aggregate).
Service invariants (tested): insert only when the booking is `completed`, `booking.student_id = caller`, `now >= ends_at + NOTE_POST_GRACE` (SC-12), and the caller's account is at least `REVIEW_MIN_ACCOUNT_AGE` (14 days) old (F7); a block does not remove an existing right to review (F7); edits only within 14 days of `created_at`.

#### `tutor_review_replies` (0048)
| Column | Type | Constraint |
|---|---|---|
| `id` | uuid PK | |
| `review_id` | uuid NOT NULL | FK RESTRICT; `uq_tutor_review_replies_review_id` — **one reply** |
| `tutor_profile_id` | uuid NOT NULL | composite FK `fk_tutor_review_replies_review_tutor_tutor_reviews`: `(review_id, tutor_profile_id) → tutor_reviews(id, tutor_profile_id)`; index `ix_tutor_review_replies_tutor_profile_id` |
| `body` | text NOT NULL | `ck_..._body_len`: `char_length(btrim(body)) BETWEEN 1 AND 1000`; passes SC-7 |
| `text_state` | moderationstate NOT NULL DEFAULT `'pending'` | `ck_..._text_state_allowed`: `IN ('pending','approved','rejected')` (moderation approved, row 15b) |
| `moderated_at` | timestamptz NULL | |
| `moderated_by` | uuid NULL | FK SET NULL; partial index `ix_tutor_review_replies_moderated_by` |

Index `ix_tutor_review_replies_pending` on `(created_at, id)` WHERE `text_state = 'pending'`.

#### `tutor_data_grants` (0049)
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | |
| `student_id` | uuid NOT NULL | FK `users.id` CASCADE (the student's own record) |
| `tutor_profile_id` | uuid NOT NULL | FK RESTRICT; plain index `ix_tutor_data_grants_tutor` (F34) |
| `scope` | tutorgrantscope NOT NULL DEFAULT `'all_subjects_derived'` | row 3b |
| `created_at` | timestamptz NOT NULL DEFAULT now() | |
| `expires_at` | timestamptz NULL | always NULL in v1; `ck_..._expires_after_created`: `expires_at IS NULL OR expires_at > created_at` |
| `revoked_at` | timestamptz NULL | `ck_..._revoked_after_created`: `revoked_at IS NULL OR revoked_at >= created_at` |
| `revoke_reason` | grantrevokereason NULL | `ck_..._revoke_reason_matches`: `(revoked_at IS NULL) = (revoke_reason IS NULL)` |

Indexes: `uq_tutor_data_grants_live` UNIQUE on `(student_id, tutor_profile_id)` WHERE `revoked_at IS NULL`; `ix_tutor_data_grants_tutor_live` on `(tutor_profile_id, created_at DESC, id)` WHERE `revoked_at IS NULL`; `ix_tutor_data_grants_student` on `(student_id, created_at DESC)`.
Validity is never a column: `core.tutor_grants.grant_status()` and its SQL mirror (§e.1).

#### `tutor_access_audit` (0049) — every tutor read of granted data
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | random, never exposed (ID-5) |
| `grant_id` | uuid NULL | FK SET NULL |
| `student_id` | uuid NOT NULL | FK `users.id` CASCADE |
| `tutor_profile_id` | uuid NULL | FK SET NULL |
| `tutor_public_name` | varchar(60) NOT NULL | snapshot ("Sara M.") |
| `action` | tutoraccessaction NOT NULL | |
| `accessed_at` | timestamptz NOT NULL DEFAULT now() | append-only |
| `created_at` | timestamptz NOT NULL DEFAULT now() | no `updated_at`: append-only, no UPDATE path in code |

Indexes: `ix_tutor_access_audit_student` on `(student_id, accessed_at DESC, id DESC)`; `ix_tutor_access_audit_tutor` on `(tutor_profile_id, accessed_at)` WHERE NOT NULL; `ix_tutor_access_audit_grant_id` on `(grant_id)` WHERE NOT NULL.

#### `tutoring_reports` (0050)
| Column | Type | Constraint / note |
|---|---|---|
| `id` | uuid PK | |
| `reporter_user_id` | uuid NULL | FK SET NULL |
| `reporter_party` | bookingparty NOT NULL | `ck_..._reporter_party_allowed`: `IN ('student','parent','tutor')` |
| `target_type` | reporttargettype NOT NULL | |
| `tutor_profile_id`, `review_id`, `reply_id`, `booking_id`, `note_id` | uuid NULL each | FKs **RESTRICT** (targets are never hard-deleted). `ck_tutoring_reports_one_target`: `num_nonnulls(...) = 1`, and the non-null column matches `target_type` |
| `target_snapshot` | jsonb NOT NULL | **PII, safeguarding**. Copy of the reported content at report time |
| `reason` | reportreason NOT NULL | |
| `details` | text NULL | `ck_..._details_len`: `char_length(details) <= 1000` |
| `state` | reportstate NOT NULL DEFAULT `'open'` | |
| `resolution` | reportresolution NULL | `ck_..._resolution_matches_state`: `(state = 'open') = (resolution IS NULL)` |
| `resolution_note` | text NULL | `ck_..._resolution_note_len`: `char_length(resolution_note) <= 1000` |
| `resolved_by` | uuid NULL | FK SET NULL; partial index `ix_tutoring_reports_resolved_by` (F34) |
| `resolved_at` | timestamptz NULL | |

Indexes: `ix_tutoring_reports_queue` on `(state, (reason = 'safety_concern') DESC, created_at, id)` (safety first, SC-10); `uq_tutoring_reports_open_per_reporter` UNIQUE on `(reporter_user_id, target_type, COALESCE(tutor_profile_id, review_id, reply_id, booking_id, note_id))` WHERE `state = 'open'`; `ix_tutoring_reports_reporter_day` on `(reporter_user_id, created_at)` (quota); one partial index per target FK, named for its column and `WHERE` it is not null: `ix_tutoring_reports_tutor_profile_id`, `_review_id`, `_reply_id`, `_booking_id`, `_note_id`.

#### `tutoring_blocks` (0050)
| Column | Type | Constraint |
|---|---|---|
| `blocker_user_id` | uuid NOT NULL | FK `users.id` CASCADE |
| `blocked_user_id` | uuid NOT NULL | FK `users.id` CASCADE |
| PK | | `pk_tutoring_blocks` on `(blocker_user_id, blocked_user_id)`; `ck_..._not_self`: `blocker_user_id <> blocked_user_id` |
| `created_at` | timestamptz NOT NULL DEFAULT now() | first block of this pair |
| `removed_at` | timestamptz NULL | unblock; re-block sets it back to NULL. Active block = `removed_at IS NULL`. Rows are never deleted, so "this student ever blocked this tutor" stays answerable (outcome exclusion, ADR-T04) |

Index `ix_tutoring_blocks_blocked` on `(blocked_user_id, blocker_user_id)`. Pairs are student ↔ teacher-with-tutor-profile only. Effects of a new or renewed block, in one transaction under the §a.4b locks (approved, row 15a): revoke the live grant (`revoke_reason = 'block'`); cancel the pair's bookings with `starts_at > now()` in `requested`/`accepted` (`cancelled_by_party = 'system'`, overrides the 24 h window); **delete the student's enrolments in every school-less class (`classes.school_id IS NULL`) owned by the tutor's user** (SC-2a); hide the tutor from the student's directory; close notes and new requests between the pair. Notes stay readable and reportable by both sides and by linked parents (SC-11).

### a.3 State machines

**Tutor listing** (`tutor_profiles.listing_state`; `paused_at` is orthogonal and tutor-owned):

| From | To | Actor | Guard and effects |
|---|---|---|---|
| `draft` | `pending_review` | tutor (T4) | verified email; headline, ≥1 subject, ≥1 mode, area, ≥1 availability rule |
| `pending_review` | `listed` | platform_admin (A3) | approval event; `documents_seen_at = now()` if `documentsSeen` else NULL; `first_listed_at = COALESCE(first_listed_at, now())` |
| `pending_review` | `rejected` | platform_admin (A4) | note required, shown to the tutor |
| `rejected` | `pending_review` | tutor (T4) | as submit |
| `listed` | `pending_review` | tutor edits a moderated field (`public_first_name`, `public_last_initial`, `headline`, `bio`, `qualification_note`, `other_mode_note`) | leaves the directory until re-approved; existing bookings stay; grants stay valid (SC-3) |
| `listed`, `pending_review`, `rejected` | `suspended` | platform_admin (A5, or A11 `tutor_suspended`) | **one transaction (§a.4b):** cancel future active bookings (`cancelled_by_party = 'platform_admin'`); revoke every live grant (`revoke_reason = 'tutor_suspended'`, SC-3); delete, from the tutor's school-less classes, the enrolments of every student who has any booking or any grant with this tutor (SC-2b); then notify the affected students and their linked parents |
| `suspended` | `listed` or `pending_review` | platform_admin (A3 reinstate) | approval event `reinstated`. To `listed` only when the profile was approved before (`first_listed_at` set) and nothing was submitted after its last approval (`submitted_at <= listed_at`); otherwise to `pending_review`, so a never-approved profile or an unreviewed moderated edit waits for an approval (§i.5, T10 review R4). The tutor is told either way, "listed again" or "back in review" (§b.4). **Restores nothing**: grants stay revoked, bookings stay cancelled, enrolments stay removed (SC-3) |
| any except `closed` | `closed` | platform_admin (A12) | same transaction as suspension with `revoke_reason = 'tutor_closed'`; sets `closed_at`; irreversible in v1 (SC-21) |

T3 (edit) on a `suspended` or `closed` profile → 409 `tutor_suspended` / `tutor_closed`; it never re-enters the admin queue (F14).
Directory visibility: `listing_state = 'listed' AND paused_at IS NULL`. New bookings and new grants require the same.
Grant validity additionally allows `pending_review` (paused allowed): see §e.1 (SC-3).

**Booking** (`tutor_bookings.state`). "Active" = `{requested, accepted}` — the exact predicate of both exclusion constraints, pinned to `core.booking.ACTIVE_STATES` by a test against both the migration text and the ORM `where` text (F20).

| From | To | Actor | Guard (all times DB `now()`) |
|---|---|---|---|
| — | `requested` | student (verified email, safety notice acknowledged), or parent with a `ParentChildLink` to the student (verified email) | tutor listed & not paused; no active block either way; subject taught; mode offered; `starts_at` is an instant from `bookable_slots`; `starts_at >= now + MIN_NOTICE`; `starts_at <= now + MAX_BOOKING_HORIZON` (28 days, SC-8); duration in `ALLOWED_DURATIONS`; live pending count for the subject student `< MAX_PENDING_PER_STUDENT` (§a.4b); requester quota (≤ 10 creations per 24 h, SC-15); parent: no `firstNote` (422 `note_not_allowed_for_parent`); DB: tutor slot free, student slot free, one pending per (student, tutor). A `requested` row holds the tutor's slot (approved, row 15d) |
| `requested` | `accepted` | tutor | `now < starts_at`; tutor not suspended/closed; listing `listed` or `pending_review`; no active block; subject still `role = student`; virtual needs an allowlisted `meeting_link`, in-person needs `location_detail` (SC-4, SC-7) |
| `requested` | `declined` | tutor | `now < starts_at`; tutor not suspended/closed |
| `requested` | `cancelled` | student, or the parent who requested it | `now < starts_at`; cancel quota (≤ 10 per 24 h) |
| `requested` | `expired` | system, lazily | `now >= starts_at`. Persisted only inside a later booking-create transaction by the same student for the same tutor (frees the one-pending index). Every read computes it (§e.1 predicates) |
| `accepted` | `cancelled` | student, or the parent who requested it | `now <= starts_at - CANCEL_CUTOFF` (24 h); later → 409 `cancel_window_closed`. Neither may cancel inside 24 h (row 18) |
| `accepted` | `cancelled` | tutor | `now < starts_at` (else 409 `already_started`); tutor not suspended/closed. Inside the window (`now > starts_at - CANCEL_CUTOFF`) a non-blank reason is required (422 `reason_required`; DB `ck_tutor_bookings_late_cancel_reason`); the reason is shown to the student and linked parents in the booking (row 18) |
| `accepted` | `cancelled` | platform_admin, system | platform_admin while `now < starts_at` (A11); a block or a suspension/close for `starts_at > now` (§a.4b) |
| `accepted` | `completed` | tutor | `now >= ends_at` (SC-17, BK-8); tutor not suspended/closed |
| `accepted` | `completed` | student, or the parent who requested it (S14, PA5) | `now >= ends_at + OUTCOME_CLAIM_AFTER` (48 h) with no tutor outcome recorded (SC-17) |
| `accepted` | `no_show` | tutor | `now >= ends_at`; tutor not suspended/closed |
| `accepted`, `no_show` | `completed` | platform_admin via A11 `booking_completed` on a `disputed_outcome` report | report targets this booking |
| `declined`, `cancelled`, `completed`, `expired` | — | — | terminal |

Derived read-time states (`core.booking.effective_state`, never stored), each with **one SQL predicate** used by every list, count and filter and pinned to the core function by a parity test (F6):

| Effective state | SQL predicate |
|---|---|
| `requested` (live pending) | `state = 'requested' AND starts_at > now()` |
| `expired` | `state = 'expired' OR (state = 'requested' AND starts_at <= now())` |
| `accepted` (upcoming or in progress) | `state = 'accepted' AND ends_at > now()` |
| `awaiting_outcome` | `state = 'accepted' AND ends_at <= now()` |
| others | `state = '<state>'` |

Transitions are compare-and-set (`UPDATE … WHERE id = :id AND state = :expected AND <guard predicates> RETURNING *`); zero rows → re-read → 200 if the target state already holds (idempotent repeat), else 409 with the specific refusal code.

**Outcome marks do not move outcome figures.** Membership of a tutor's outcome cohort is decided by `accepted_at IS NOT NULL AND state IN ('accepted','completed','no_show') AND ends_at <= now()` (ADR-T04). Neither `completed`, `no_show`, a tutor-initiated block nor a dispute changes it (F1, RF-4).

**Notes** — `core.booking.can_post_note` (SC-8):

| Effective state | Student or tutor may post |
|---|---|
| `requested` (live) | yes |
| `accepted` (before `ends_at`) | yes |
| `awaiting_outcome`, `completed` | until `ends_at + NOTE_POST_GRACE` (7 days) |
| `no_show`, `declined`, `cancelled`, `expired` | no |
| any state, if: active block between the pair, tutor suspended or closed, or `notes_frozen_at IS NOT NULL` | no |

Reading and reporting notes are always allowed to those who can see the booking. A student's first note also requires the safety notice (row 16 ii).

**Review text** (`moderationstate`): `none` (stars only) · `pending` → `approved` | `rejected` (admin). Editing text inside the 14-day window returns it to `pending`. Stars count in aggregates from insert until `removed_at` (one latest review per student, SC-16). **Reply:** `pending` → `approved` | `rejected`.

**Report:** `open` → `dismissed` | `actioned` (with `resolution`). Resolution clears `tutor_bookings.notes_frozen_at` for the target booking.

### a.4 Exclusion constraints and other non-trivial DDL

All DDL lives in Alembic revisions; no `supabase/migrations`, no hand-applied SQL.

```python
# 0044_tutoring_enums_ext — first statement of the chain
op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")   # downgrade never drops it (F35)

# 0045_tutor_profiles
op.create_exclude_constraint(
    "excl_tutor_availability_rules_no_overlap", "tutor_availability_rules",
    ("tutor_profile_id", "="), ("iso_weekday", "="),
    (sa.text("int4range(start_minute, end_minute, '[)')"), "&&"),
    using="gist",
)

# 0047_tutor_bookings — slot is a STORED generated column:
#   sa.Column("slot", postgresql.TSTZRANGE(),
#             sa.Computed("tstzrange(starts_at, ends_at, '[)')", persisted=True), nullable=False)
op.create_exclude_constraint(
    "excl_tutor_bookings_tutor_slot", "tutor_bookings",
    ("tutor_profile_id", "="), ("slot", "&&"),
    using="gist", where=sa.text("state IN ('requested', 'accepted')"),
)
op.create_exclude_constraint(
    "excl_tutor_bookings_student_slot", "tutor_bookings",
    ("student_id", "="), ("slot", "&&"),
    using="gist", where=sa.text("state IN ('requested', 'accepted')"),
)
op.create_index(
    "uq_tutor_bookings_one_pending", "tutor_bookings",
    ["student_id", "tutor_profile_id"], unique=True,
    postgresql_where=sa.text("state = 'requested'"),
)
```

**Test databases built with `create_all` (F2).** About 88 test files create a
fresh database (`CREATE DATABASE "lemely_test_…"`) and call
`Base.metadata.create_all(engine)` (e.g. `tests/test_db_schema.py:319-337`,
`tests/test_web_platform_admin.py:83-104`); only `migrated_sessionmaker`
(`tests/conftest.py:617`) runs Alembic. A fresh database has no `btree_gist`,
so `create_all` of the ExcludeConstraints fails (`data type uuid has no default
operator class for access method "gist"`, probe in ADVERSARIAL F2).
**Decision:** the ORM declares the ExcludeConstraints (so `create_all`
databases enforce the same rules the tests depend on), and the new models
module attaches a **table-level** DDL listener:

```python
# lemely/db/models/tutoring.py (new; registered in import_all_models)
_BTREE_GIST = DDL("CREATE EXTENSION IF NOT EXISTS btree_gist").execute_if(dialect="postgresql")
event.listen(TutorAvailabilityRule.__table__, "before_create", _BTREE_GIST)
event.listen(TutorBooking.__table__, "before_create", _BTREE_GIST)
```

Rejected: (a) a `before_create` listener on `Base.metadata` in
`lemely/db/base.py` (works, but edits the most-imported hot file for a
tutoring concern); (b) declaring the constraints in Alembic only (`create_all`
databases would then silently allow double booking, so a tutoring test on the
common fixture would go green on a broken invariant); (c) installing the
extension in `template1` from `conftest.py` (mutates every developer's local
cluster and may lack privilege on Supabase). The listener needs no hot-file
edit beyond the one import line in `lemely/db/models/__init__.py`
(`import_all_models`, `:94`), owned by the wave-1 implementer. CI runs
`postgres:16` as `POSTGRES_USER: postgres` (superuser, `ci.yml:28-32`);
locally the extension is trusted and creatable by the non-superuser `postgres`
role (verified 2026-10-25, Supabase `postgres:17.6.1.143`). Proving test:
`tests/test_db_tutoring_schema.py::test_create_all_on_fresh_database_installs_btree_gist`
(fresh `CREATE DATABASE` + `create_all` succeeds and both exclusion
constraints exist; red case: with the listener removed, `create_all` raises).

**`alembic check` is not a guard here (F20).** No gate runs it (`scripts/check.sh`, `ci.yml`), and the comparator reports 0 diffs with or without the ExcludeConstraints, for Computed columns, partial enum predicates and COALESCE expression indexes. The real guards are the migration tests, which assert by name in `pg_constraint`/`pg_indexes` and assert that `pg_get_constraintdef` contains `EXCLUDE USING gist`, the `&&` operator and both `requested` and `accepted` in the predicate. (`tests/test_flashcard_schema.py:205` claims `check.sh` runs `alembic check`; that comment is stale and out of scope here.)

**Verified 2026-10-25** against the local stack (PostgreSQL 17.6, role `postgres`, `rolsuper = false`, rolled-back transactions): overlapping active tutor slot → `23P01` on `excl_tutor_bookings_tutor_slot`; overlapping slot for the same student with another tutor → `23P01` on `excl_tutor_bookings_student_slot`; second pending request for the same pair → `23505` on `uq_tutor_bookings_one_pending`; adjacent `[)` slots accepted; a cancelled row frees the slot; overlapping availability rules → `23P01`; adjacent rules accepted.

Error mapping (repository layer, by `IntegrityError.orig.diag.constraint_name`):
`excl_tutor_bookings_tutor_slot` → 409 `slot_taken`; `excl_tutor_bookings_student_slot` → 409 `student_busy`; `uq_tutor_bookings_one_pending` → 409 `already_pending`; `uq_tutor_data_grants_live` → return the existing grant (200); `uq_tutor_reviews_booking_id` → 409 `review_exists`; `uq_tutor_review_replies_review_id` → 409 `reply_exists`; `uq_tutoring_reports_open_per_reporter` → 409 `report_exists`; `excl_tutor_availability_rules_no_overlap` → 422 `overlapping_rules`.

### a.4b Lock protocol and action guards (SC-4)

Every multi-row tutoring write takes locks in this global order, so no two paths can deadlock:
1. `tutor_profiles` row (`FOR SHARE` for actions by students, parents and the tutor on one booking or grant; `FOR UPDATE` for block, suspension and close).
2. the subject student's `users` row (`FOR UPDATE`, booking create only: serialises the live pending count, precedent `InviteService.mint_parent_invite`, F6/BK-2).
3. `pg_advisory_xact_lock(hashtextextended(student_id::text || ':' || tutor_profile_id::text, 0))` — the pair lock.
4. a parent requester's link via `ParentLinkService.lock_link_in_session(session, parent_id, child_id)` (`SELECT … FOR SHARE`; new method, the class stays the single `parent_child_links` query, `parent_repo.py:8-13`, F32). An unlink (`DELETE`) then waits for, or is waited on by, the insert (BK-3).
5. booking rows (compare-and-set).

| Action | Locks | Re-checked inside the transaction and in the CAS `WHERE` |
|---|---|---|
| Booking create (SP6) | 1 share, 2, 3, 4 (parent) | listed & not paused, no active block, link present (parent), live pending count, quotas, lazy expiry of the pair's stale `requested` row |
| Accept, decline, complete, no-show (T11, T12, T14, T15) | 1 share, 3 | not suspended/closed, no active block (accept), subject still a student (accept) |
| Cancel (S3, PA4, T13) | 1 share, 3, 4 (parent) | the party's window (§a.3: student and requesting parent until `starts_at - 24 h`; tutor until `starts_at`, with a reason inside 24 h), requester (parent), cancel quota |
| Student/parent complete (S14, PA5) | 1 share, 3, 4 (parent) | `awaiting_outcome` ≥ 48 h, no tutor outcome |
| Note post (S5, T17) | 1 share, 3 | `can_post_note` |
| Grant create (S9) | 1 share, 3 | listed & not paused, no active block |
| Block (B2) | 1 update, 3 | sweeps grants, future bookings, school-less enrolments |
| Suspend, close (A5, A11, A12) | 1 update | sweeps every pair of that tutor |

Every tutor **write** route (T3–T7, T11–T15, T17, T18, B2 by a tutor) returns 409 `tutor_suspended` (or `tutor_closed`) for a suspended or closed profile (CB-7). T8 omits `OutcomesDTO` unless the profile is `listed` or `pending_review` (ID-7).

### a.5 Privacy-sensitive columns (summary)
- **Public on the open web:** `public_first_name`, `public_last_initial`, `headline`, modes, `area_code` (city), subjects, `rating_avg`/`rating_count`. Nothing else, ever.
- **Logged-in, participants and linked parents only:** `meeting_link`, `location_detail` (after accept), notes `body`.
- **Admin only:** evidence files, approval notes, `target_snapshot`, account email on X-05.
- **Student-owned record, readable by the student and (read-only, row 16 i) linked parents:** grants, `tutor_access_audit`.
- **Student only:** `student_tutoring_preferences`.
- Never exposed by any tutoring route: `users.email` (except to platform_admin on X-05), `users.phone`, a tutor's `users.id` to any non-admin DTO (SC-19), whether a student has linked parents to any tutor-facing DTO (SC-9), a student's name to anyone but their tutor (booking/grant), their parents and themselves. Reviews show "A student" and a quarter, never a name (SC-12).

---

## b. API contract

### b.1 Files
| File | Contents |
|---|---|
| `lemely/web/routers/tutoring_public.py` | `/api/public/tutors*`, `/api/public/tutoring-areas` (PUBLIC) |
| `lemely/web/routers/tutoring_directory.py` | `/api/tutors*`, `POST /api/bookings` (STUDENT_OR_PARENT) |
| `lemely/web/routers/student_tutoring.py` | `/api/student/bookings*`, `/api/student/reviews/*`, `/api/student/tutor-grants*`, `/api/student/tutor-access-log`, `/api/student/tutor-access/classes`, `/api/student/tutoring-settings`, `/api/student/tutoring-safety-notice` |
| `lemely/web/routers/student_classes.py` (existing) | **one new route** `DELETE /api/student/classes/{class_id}` (SC-2c) |
| `lemely/web/routers/tutor.py` | `/api/tutor/*` (TEACHER + owns a profile) |
| `lemely/web/routers/parent_tutoring.py` | `/api/parent/children/{child_id}/bookings*`, `/tutor-grants`, `/tutor-access-log` (new routes; `parent.py` untouched) |
| `lemely/web/routers/tutoring_safety.py` | `/api/tutoring/reports`, `/api/tutoring/blocks*` |
| `lemely/web/routers/admin_tutoring.py` | `/api/admin/tutors*`, `/api/admin/tutoring/*` (`admin.py` untouched) |
| `lemely/web/schemas_tutoring.py`, `lemely/web/schemas_tutoring_admin.py` | DTOs (§b.3) |
| `lemely/web/student_detail_view.py` | tutor projection of the T-05 DTO (§e.2) |
| `lemely/web/tutoring_notify.py` | after-commit inbox fan-out through `notify_safely` (§b.4) |
| `lemely/web/tutoring_email.py` | the sweeper job that delivers `email_outbox` rows (§b.4) |

All routers are included in `lemely/web/app.py` beside the existing `include_router` calls.
**Build layout (rev 3):** `BUILD/tutoring/PLAN.md` §2 splits these routers, repositories and test files further so that no two parallel tasks own one file. Every route, path, guard, DTO and behaviour above is unchanged; only the module that holds it differs. Where the two disagree on a file name, PLAN.md wins.

### b.2 Routes

Legend: **C** = cursor-paged. **V** = `require_verified_email` (403 `email_unverified`). **NS** = response carries `Cache-Control: private, no-store` (SC-26). **PLAN rev 2 (P12):** the marks below and the §b.5 list disagree (§b.5 also covers notes and every `BookingDTO`/`GrantDTO`/`AccessLogPageDTO`/`ClassAccessDTO` response, several of which carry no mark), so **every non-PUBLIC tutoring route (67 of 70, including S16 and S17) is NS, on every response status**. That is a superset of both lists; the marks are kept for reference only. Status codes list the non-guard outcomes; every non-PUBLIC route also returns 401 (no/invalid token) and 403 (role not in guard) from `require_role` before the handler runs.

#### Public (no auth) — `Cache-Control: public, max-age=60` on all three, and the Workers read-through cache (§b.5)
| # | Method · Path | Request | Response | Codes |
|---|---|---|---|---|
| P1 | `GET /api/public/tutors` **C** | `subject?`, `mode?` (repeatable, OR), `area?`, `minRating?` (1.0–5.0, step 0.5) | `PublicDirectoryPageDTO` (`facets` on the first page only) | 200, 422. `X-Robots-Tag: noindex`. No availability filter (row 5b) |
| P2 | `GET /api/public/tutors/{tutor_id}` | — | `PublicTutorCardDTO` (`TutorCardDTO` + `indexable`; the only DTO that carries it, row 17) | 200; 404 unless listed-and-not-paused (one predicate; identical 404 body for unknown, unlisted, paused, suspended, closed, PP-6). Same headers. The edge worker's indexing lookup (§b.5) reads this route |
| P3 | `GET /api/public/tutoring-areas` | — | `AreaListDTO` (every entry of `lemely/data/tutoring_areas.json`) | 200 (F13) |

Sort: `rank_score DESC, first_listed_at ASC, id ASC`; cursor `(rank_score, first_listed_at, id)` (F10). `minRating` predicate: `rating_count >= 3 AND rating_avg >= :min` ("New" tutors excluded, F25).

#### Logged-in directory and booking request — `STUDENT_OR_PARENT`
| # | Method · Path | Request | Response | Codes |
|---|---|---|---|---|
| SP1 | `GET /api/tutors` **C** | P1 filters + `day?` (repeatable 1–7) + `timeOfDay?` (repeatable `morning`/`afternoon`/`evening`) | `DirectoryPageDTO` | 200, 422. Hides tutors in an active block with the caller (students only; parents hold no blocks) |
| SP2 | `GET /api/tutors/{tutor_id}` **V** | — | `TutorProfileDTO` | 200; 404 unlisted/paused/blocked |
| SP3 | `GET /api/tutors/{tutor_id}/reviews` **C V** | — | `ReviewsPageDTO` (newest first; text only if approved; reply only if approved) | 200, 404 |
| SP4 | `GET /api/tutors/{tutor_id}/outcomes` **V** | — | `OutcomesDTO` | 200, 404 |
| SP5 | `GET /api/tutors/{tutor_id}/slots` **V** | `from` (tutor-zone date, ≥ today), `days` (1–28, default 14; `from + days ≤ today + 28`), `durationMinutes` (45/60/90/120) | `SlotsDTO` | 200, 404, 422 |
| SP6 | `POST /api/bookings` **V** | `BookingCreateDTO` | `BookingDTO` **NS** | 201; 403 `not_linked` (parent, child not linked) / `not_self` (student sent another `studentId`); 404 tutor; 409 `tutor_not_listed`, `blocked`, `not_bookable`, `beyond_horizon`, `slot_taken`, `student_busy`, `already_pending`, `pending_limit`, `safety_notice_required` (student requester only); 422 incl. `note_not_allowed_for_parent`, `contact_details_not_allowed`; 429 `too_many_requests` |

Time-of-day buckets (tutor-zone wall clock, `core.tutor_directory.TIME_OF_DAY_MINUTES`): morning 06:00–12:00, afternoon 12:00–17:00, evening 17:00–22:00. A tutor matches if any weekly rule overlaps any selected (day, bucket). The UI labels this "Usually available".

#### Student — `STUDENT`
| # | Method · Path | Request | Response | Codes |
|---|---|---|---|---|
| S1 | `GET /api/student/bookings` **C NS** | `when=upcoming\|past` | `BookingsPageDTO`. Upcoming = effective `requested`/`accepted`/`awaiting_outcome` with `ends_at > split`; past = the rest; `split` is fixed in the cursor (F25). upcoming: `starts_at ASC, id`; past: `starts_at DESC, id DESC` | 200 |
| S2 | `GET /api/student/bookings/{booking_id}` **NS** | — | `BookingDTO` | 200, 404 |
| S3 | `POST /api/student/bookings/{booking_id}/cancel` **NS** | `BookingReasonDTO` | `BookingDTO` | 200, 404, 409 `illegal_transition`, `cancel_window_closed`; 422; 429 |
| S4 | `GET /api/student/bookings/{booking_id}/notes` **C NS** | — | `NotesPageDTO` (oldest first) | 200, 404 |
| S5 | `POST /api/student/bookings/{booking_id}/notes` **NS** | `NoteCreateDTO` | `NoteDTO` | 201, 404, 409 `notes_closed`, `safety_notice_required`; 422 `contact_details_not_allowed` |
| S6 | `POST /api/student/bookings/{booking_id}/review` **V** | `ReviewCreateDTO` | `MyReviewDTO` | 201, 404, 409 `not_completed`, `review_not_open_yet` (before `ends_at + 7 d`), `account_too_new`, `review_exists`; 422 |
| S7 | `PATCH /api/student/reviews/{review_id}` **V** | `ReviewUpdateDTO` | `MyReviewDTO` | 200, 404, 409 `edit_window_closed`; 422 |
| S8 | `GET /api/student/tutor-grants` **NS** | — | `GrantsDTO` (live first, then ended, newest first; max 200) | 200 |
| S9 | `POST /api/student/tutor-grants` **V NS** | `GrantCreateDTO` | `GrantDTO` | 201 new; 200 existing live grant; 404 tutor; 409 `tutor_not_listed`, `blocked` |
| S10 | `POST /api/student/tutor-grants/{grant_id}/revoke` **NS** | — | `GrantDTO` | 200 (idempotent), 404 |
| S11 | `GET /api/student/tutor-access-log` **C NS** | `tutorId?` | `AccessLogPageDTO` (`accessed_at DESC, id DESC`) | 200 |
| S12 | `GET /api/student/tutoring-settings` | — | `TutoringSettingsDTO` | 200 |
| S13 | `PUT /api/student/tutoring-settings` | `TutoringSettingsUpdateDTO` | `TutoringSettingsDTO` | 200, 422 |
| S14 | `POST /api/student/bookings/{booking_id}/complete` **NS** | — | `BookingDTO` | 200, 404, 409 `outcome_claim_not_open` (SC-17) |
| S15 | `POST /api/student/tutoring-safety-notice` | — | `TutoringSettingsDTO` | 200 (idempotent; first call sets `safetyNoticeAcknowledgedAt`) (row 16 ii) |
| S16 | `GET /api/student/tutor-access/classes` **NS** | — | `ClassAccessDTO` (classes whose teacher can see the caller's progress through the roster) | 200 (SC-2e) |
| S17 | `DELETE /api/student/classes/{class_id}` | — | — | 204; 404 unless the caller is currently enrolled in that class **and** it has `school_id IS NULL` (SC-2c) |

#### Tutor — `TEACHER` + caller owns a `tutor_profiles` row
(Every route resolves the profile from `auth.user_id` via `TutorProfileRepository.for_user`; a teacher without one gets 404 `{"code":"no_tutor_profile"}` except T2.)

| # | Method · Path | Request | Response | Codes |
|---|---|---|---|---|
| T1 | `GET /api/tutor/profile` | — | `TutorOwnProfileDTO` | 200, 404 |
| T2 | `POST /api/tutor/profile` | `TutorProfileCreateDTO` | `TutorOwnProfileDTO` (`draft`) | 201; 409 `profile_exists`; 422 (incl. name charset, `contact_details_not_allowed`) |
| T3 | `PATCH /api/tutor/profile` | `TutorProfileUpdateDTO` (incl. `paused`, `indexable`; neither is moderated) | `TutorOwnProfileDTO` + `reReviewRequired` | 200, 404, 409 `tutor_suspended`/`tutor_closed`, 422 |
| T4 | `POST /api/tutor/profile/submit` **V** | — | `TutorOwnProfileDTO` | 200, 404, 409 `incomplete_profile`, `illegal_transition` |
| T5 | `PUT /api/tutor/profile/availability` | `AvailabilityReplaceDTO` (0–42 rules) | `AvailabilityRuleDTO[]` | 200, 404, 409 suspended/closed, 422 `overlapping_rules` |
| T6 | `POST /api/tutor/profile/evidence` | multipart `file`, `description?` | `EvidenceDTO` | 201, 404, 409 `evidence_limit`, suspended/closed; 413; 415 (sniffed type not allowed) |
| T7 | `DELETE /api/tutor/profile/evidence/{evidence_id}` | — | — | 204, 404 (O20), 409 suspended/closed |
| T8 | `GET /api/tutor/profile/preview` | — | `TutorPreviewDTO` (`TutorProfileDTO` + `outcomes: OutcomesDTO \| None`; None unless listed or pending_review) | 200, 404 |
| T9 | `GET /api/tutor/bookings` **C NS** | `when=upcoming\|past`, `state?` (an **effective** state, filtered by its §a.3 predicate) | `BookingsPageDTO` | 200, 404 |
| T10 | `GET /api/tutor/bookings/{booking_id}` **NS** | — | `BookingDTO` (with `studentShared`) | 200, 404 |
| T11 | `POST /api/tutor/bookings/{booking_id}/accept` **NS** | `BookingAcceptDTO` | `BookingDTO` | 200, 404, 409 `illegal_transition`, `already_started`, `tutor_suspended`, `access_ended` (block); 422 missing/disallowed link (`meeting_link_not_allowed`) or location (`contact_details_not_allowed`) |
| T12 | `POST /api/tutor/bookings/{booking_id}/decline` **NS** | `BookingReasonDTO` | `BookingDTO` | 200, 404, 409, 422 |
| T13 | `POST /api/tutor/bookings/{booking_id}/cancel` **NS** | `BookingReasonDTO` (`reason` required inside 24 h of the start, row 18) | `BookingDTO` | 200, 404, 409 `illegal_transition`, `already_started`, `tutor_suspended`/`tutor_closed`; 422 `reason_required`, `contact_details_not_allowed`; 429 |
| T14 | `POST /api/tutor/bookings/{booking_id}/complete` **NS** | — | `BookingDTO` | 200, 404, 409 `not_ended` |
| T15 | `POST /api/tutor/bookings/{booking_id}/no-show` **NS** | — | `BookingDTO` | 200, 404, 409 `not_ended` |
| T16 | `GET /api/tutor/bookings/{booking_id}/notes` **C NS** | — | `NotesPageDTO` | 200, 404 |
| T17 | `POST /api/tutor/bookings/{booking_id}/notes` **NS** | `NoteCreateDTO` | `NoteDTO` | 201, 404, 409 `notes_closed`; 422 |
| T18 | `POST /api/tutor/reviews/{review_id}/reply` | `ReplyCreateDTO` | `ReplyDTO` | 201, 404 (review not about this tutor), 409 `reply_exists`, suspended/closed; 422 |
| T19 | `GET /api/tutor/students` **C NS** | — | `TutorStudentPageDTO` (`grantedAt DESC, grantId`); names, grant date, upcoming-session count; **no analytics**. Writes one `list` audit row per student on the page | 200, 404 |
| T20 | `GET /api/tutor/students/{student_id}` **NS** | — | `TutorStudentDetailDTO` | 200; 403 `{"code":"access_ended"}` when a grant existed for **this caller's profile** and this student but is not valid now (SC-11; the reason is never shown to the tutor); 404 when no grant ever existed for this pair or the id is unknown; 422 malformed id. **Writes one `detail` audit row before loading data; audit failure → 500, no body** |
| T21 | `GET /api/tutor/reviews` **C** | — | `TutorReviewsPageDTO` (own reviews, newest first; approved text only; the tutor's own reply in any moderation state) | 200, 404 (F13) |

#### Parent — `PARENT` (new routes; existing `/api/parent/*` routes unchanged)
| # | Method · Path | Request | Response | Codes |
|---|---|---|---|---|
| PA1 | `GET /api/parent/children/{child_id}/bookings` **C NS** | `when=upcoming\|past` | `BookingsPageDTO` | 200; 403 not linked; 404 unknown child |
| PA2 | `GET /api/parent/children/{child_id}/bookings/{booking_id}` **NS** | — | `BookingDTO` | 200, 403, 404 |
| PA3 | `GET /api/parent/children/{child_id}/bookings/{booking_id}/notes` **C NS** | — | `NotesPageDTO` (`canPost` always false) | 200, 403, 404 |
| PA4 | `POST /api/parent/children/{child_id}/bookings/{booking_id}/cancel` **NS** | `BookingReasonDTO` | `BookingDTO` | 200, 403 `not_requester`, 404, 409 `illegal_transition`, `cancel_window_closed` (inside 24 h, row 18), 429 |
| PA5 | `POST /api/parent/children/{child_id}/bookings/{booking_id}/complete` **NS** | — | `BookingDTO` | 200, 403 `not_requester`, 404, 409 `outcome_claim_not_open` (SC-17) |
| PA6 | `GET /api/parent/children/{child_id}/tutor-grants` **NS** | — | `GrantsDTO` (the child's grants, read-only; `alsoTeachesClasses` always empty) | 200, 403, 404 (row 16 i) |
| PA7 | `GET /api/parent/children/{child_id}/tutor-access-log` **C NS** | `tutorId?` | `AccessLogPageDTO` (the child's log) | 200, 403, 404 (row 16 i) |

Parents browse and request through SP1–SP6 (with `studentId`). A parent's reads on PA6/PA7 write no `tutor_access_audit` row (that log records tutor reads only).

#### Safety — reports and blocks
| # | Method · Path | Guard | Request | Response | Codes |
|---|---|---|---|---|---|
| R1 | `POST /api/tutoring/reports` | `TUTORING_PARTY` {student, parent, teacher} | `ReportCreateDTO` | `ReportReceiptDTO` | 201; 404 target not visible to caller (O12, O19); 409 `report_exists`; 422; 429 (≤ 20 per 24 h). **Not** behind `require_verified_email`: a report is a safety path (SC-15 exception) |
| B1 | `GET /api/tutoring/blocks` | `STUDENT_OR_TEACHER` | — | `BlocksDTO` (active blocks only) | 200 |
| B2 | `POST /api/tutoring/blocks` | `STUDENT_OR_TEACHER` | `BlockCreateDTO` (`tutorId` from a student, `studentId` from a tutor; SC-19) | `BlockDTO` | 201; 200 already blocked; 404 not a blockable counterpart (O13); 409 `tutor_suspended` (tutor caller); 422 wrong field for the caller's role |
| B3 | `DELETE /api/tutoring/blocks/{counterpart_id}` | `STUDENT_OR_TEACHER` | — | — | 204, 404. `counterpart_id` is a tutor profile id (student caller) or a student id (tutor caller). Sets `removed_at`; restores nothing |

#### Platform admin — `PLATFORM_ADMIN`
| # | Method · Path | Request | Response | Codes |
|---|---|---|---|---|
| A1 | `GET /api/admin/tutors` **C** | `state=…` (default `pending_review`) | `AdminTutorPageDTO` (incl. `emailDelivery: "provider"\|"mock"`, SC-6) | 200 |
| A2 | `GET /api/admin/tutors/{tutor_id}` | — | `AdminTutorDetailDTO` (profile, account email, evidence with 300 s attachment signed URLs, approval history, open report count). Writes one `tutoring_admin_access` `evidence_open` row per signed URL issued | 200, 404 |
| A3 | `POST /api/admin/tutors/{tutor_id}/approve` | `AdminApproveDTO` | `AdminTutorDetailDTO` | 200 (`pending_review` → listed; `suspended` → listed as `reinstated`), 404, 409 |
| A4 | `POST /api/admin/tutors/{tutor_id}/reject` | `AdminNoteDTO` | `AdminTutorDetailDTO` | 200, 404, 409 |
| A5 | `POST /api/admin/tutors/{tutor_id}/suspend` | `AdminNoteDTO` | `AdminTutorDetailDTO` | 200, 404, 409 |
| A6 | `GET /api/admin/tutoring/moderation` **C** | `kind=review\|reply\|all` | `ModerationPageDTO` (oldest first) | 200 |
| A7 | `POST /api/admin/tutoring/reviews/{review_id}/moderate` | `ReviewModerateDTO` | `AdminReviewDTO` | 200 (also when the same decision already holds on the same text), 404, 409 `text_changed` (the stored text is not the one whose revision the admin sent, RF-7) |
| A8 | `POST /api/admin/tutoring/replies/{reply_id}/moderate` | `ReplyModerateDTO` | `AdminReplyDTO` | 200, 404, 409 |
| A9 | `GET /api/admin/tutoring/reports` **C** | `state=…` (default open) | `ReportPageDTO` (safety concerns first) | 200 |
| A10 | `GET /api/admin/tutoring/reports/{report_id}` **NS** | — | `ReportDetailDTO` (snapshot; for booking/note targets the booking summary and its notes thread, the only admin path to notes). Writes one `report_thread_view` row | 200, 404 |
| A11 | `POST /api/admin/tutoring/reports/{report_id}/resolve` | `ReportResolveDTO` | `ReportDetailDTO` | 200, 404, 409 `already_resolved` / `resolution_not_applicable` (e.g. `booking_cancelled` after `starts_at`; `booking_completed` unless the target booking is `awaiting_outcome` or `no_show`) |
| A12 | `POST /api/admin/tutors/{tutor_id}/close` | `AdminNoteDTO` | `AdminTutorDetailDTO` | 200, 404, 409 `already_closed` (SC-21) |

**Route count: 70** (PUBLIC 3, STUDENT_OR_PARENT 6, STUDENT 17, TEACHER 21, PARENT 7, TUTORING_PARTY 1, STUDENT_OR_TEACHER 3, PLATFORM_ADMIN 12).

### b.3 DTOs (`schemas_tutoring.py`, `schemas_tutoring_admin.py`; all `ApiModel`)

```python
TutoringModeLit = Literal["virtual", "in_person", "other"]
EffectiveStateLit = Literal["requested", "accepted", "declined", "cancelled", "completed",
                            "no_show", "expired", "awaiting_outcome"]
ViewerActionLit = Literal["accept", "decline", "cancel", "cancel_with_reason", "complete", "no_show",
                          "review", "post_note"]
# "cancel_with_reason": tutor viewer only, accepted booking inside 24 h of the start (row 18);
# the client must collect a reason. "cancel" and "cancel_with_reason" are never both present.

class SubjectRefDTO(ApiModel):   code: str; name: str
class AreaRefDTO(ApiModel):      code: str; name: str
class AreaListDTO(ApiModel):     items: list[AreaRefDTO]
class RatingDTO(ApiModel):       state: Literal["new", "rated"]; average: float | None  # 1 dp, None when new
                                 count: int          # distinct students (SC-16)
class TutorCardDTO(ApiModel):    tutorId: str; publicName: str   # profile id, never users.id (SC-19)
                                 headline: str; subjects: list[SubjectRefDTO]
                                 modes: list[TutoringModeLit]; area: AreaRefDTO; rating: RatingDTO
class PublicTutorCardDTO(TutorCardDTO): indexable: bool   # P2 only (row 17); read by the edge worker
class DirectoryFacetsDTO(ApiModel): subjects: list[SubjectRefDTO]; areas: list[AreaRefDTO]
class PublicDirectoryPageDTO(ApiModel): items: list[TutorCardDTO]; nextCursor: str | None
                                        facets: DirectoryFacetsDTO | None
class DirectoryPageDTO(PublicDirectoryPageDTO): pass
class AvailabilityRuleDTO(ApiModel): isoWeekday: int; startMinute: int; endMinute: int
class TutorProfileDTO(TutorCardDTO): bio: str; qualificationNote: str | None
                                     otherModeNote: str | None; documentsSeen: bool
                                     availability: list[AvailabilityRuleDTO]; zone: str; zoneLabel: str
                                     listedSince: str | None  # "YYYY-MM" from first_listed_at; None until the first approval (never-listed profiles have no value)
class ReplyDTO(ApiModel):        replyId: str; body: str; textState: Literal["pending", "approved", "rejected"]
                                 createdAt: str
class ReviewDTO(ApiModel):       reviewId: str; stars: int; text: str | None
                                 period: str        # quarter, "Jul–Sep 2026" (SC-12)
                                 reply: ReplyDTO | None
class ReviewsPageDTO(ApiModel):  items: list[ReviewDTO]; nextCursor: str | None
class TutorReviewItemDTO(ReviewDTO): textState: Literal["none", "pending", "approved", "rejected"]
                                     # text is None unless approved; reply in any state (own)
class TutorReviewsPageDTO(ApiModel): items: list[TutorReviewItemDTO]; nextCursor: str | None
class OutcomeBucketDTO(ApiModel): grade: str; count: int
class OutcomeDistributionDTO(ApiModel): state: Literal["insufficient", "sufficient"]; k: int
                                        nGraded: int | None; nWithoutGrade: int | None   # both None when insufficient
                                        buckets: list[OutcomeBucketDTO]                    # empty when insufficient
class OutcomeChangeDTO(ApiModel): state: Literal["insufficient", "sufficient"]; k: int
                                  nPaired: int | None; higher: int | None; same: int | None; lower: int | None
class SubjectOutcomeDTO(ApiModel): subject: SubjectRefDTO; distribution: OutcomeDistributionDTO
                                   change: OutcomeChangeDTO
class OutcomesDTO(ApiModel):     tutorId: str; ladder: list[str]
                                 duringWindowDays: int; beforeLookbackDays: int   # captions (F10)
                                 subjects: list[SubjectOutcomeDTO]
class TutorPreviewDTO(ApiModel): profile: TutorProfileDTO; outcomes: OutcomesDTO | None
class SlotDTO(ApiModel):         startsAt: str; endsAt: str
class SlotsDTO(ApiModel):        tutorId: str; zone: str; zoneLabel: str; durationMinutes: int
                                 windowStart: str; windowEnd: str; slots: list[SlotDTO]
class BookingCreateDTO(ApiModel): tutorId: str; studentId: str | None = None
                                  subjectCode: str; mode: TutoringModeLit; startsAt: str
                                  durationMinutes: int; otherModeNote: str | None = None
                                  firstNote: str | None = None  # student only; parent → 422
class BookingStudentDTO(ApiModel): studentId: str; displayName: str   # student_label(), never email (F12)
class BookingReviewRefDTO(ApiModel): reviewId: str; stars: int
                                     textState: Literal["none", "pending", "approved", "rejected"]
                                     editableUntil: str
class BookingDTO(ApiModel):      bookingId: str; tutor: TutorCardDTO; student: BookingStudentDTO
                                 requestedBy: Literal["student", "parent"]; subject: SubjectRefDTO
                                 mode: TutoringModeLit; startsAt: str; endsAt: str
                                 effectiveState: EffectiveStateLit
                                 area: AreaRefDTO
                                 meetingLink: str | None          # accepted+ only; participants and linked parents
                                 locationDetail: str | None       # accepted+ only; participants and linked parents
                                 otherModeNote: str | None; declineReason: str | None
                                 cancelReason: str | None         # system reasons → "Cancelled" for the tutor viewer
                                 cancelledBy: Literal["student", "parent", "tutor", "platform_admin", "system"] | None
                                 cancelledLate: bool              # tutor cancelled inside 24 h of the start (row 18);
                                                                  # derived: cancelled_by_party = 'tutor' AND
                                                                  # cancelled_at > starts_at - CANCEL_CUTOFF
                                 completedBy: Literal["student", "parent", "tutor", "platform_admin"] | None
                                 notesFrozen: bool
                                 allowedActions: list[ViewerActionLit]
                                 review: BookingReviewRefDTO | None    # student viewer only; null otherwise (SC-12)
                                 reviewOpensAt: str | None             # student viewer only
                                 studentShared: bool | None            # tutor viewer only: grant predicate, no audit row (F13)
                                 createdAt: str
class BookingsPageDTO(ApiModel): items: list[BookingDTO]; nextCursor: str | None
class BookingAcceptDTO(ApiModel): meetingLink: str | None = None; locationDetail: str | None = None
class BookingReasonDTO(ApiModel): reason: str | None = None   # <= 300, SC-7
class NoteDTO(ApiModel):         noteId: str; authorParty: Literal["student", "tutor"]
                                 authorName: str; body: str | None; hidden: bool; createdAt: str
class NotesPageDTO(ApiModel):    items: list[NoteDTO]; nextCursor: str | None; canPost: bool
class NoteCreateDTO(ApiModel):   body: str   # 1..2000 after strip
class ReviewCreateDTO(ApiModel): stars: int; text: str | None = None
class ReviewUpdateDTO(ApiModel): stars: int | None = None; text: str | None = None; clearText: bool = False
class MyReviewDTO(ApiModel):     reviewId: str; bookingId: str; stars: int; text: str | None
                                 textState: Literal["none", "pending", "approved", "rejected"]; editableUntil: str
class ReplyCreateDTO(ApiModel):  body: str
GrantStatusLit = Literal["active", "revoked", "expired", "blocked", "tutor_suspended", "tutor_closed",
                         "tutor_unavailable"]
class GrantDTO(ApiModel):        grantId: str; tutor: TutorCardDTO; createdAt: str; revokedAt: str | None
                                 status: GrantStatusLit; scope: Literal["all_subjects_derived"]
                                 alsoTeachesClasses: list[str]   # student viewer: class names where this tutor's
                                                                 # user is the class teacher (SC-2e); [] for parents
class GrantsDTO(ApiModel):       items: list[GrantDTO]
class GrantCreateDTO(ApiModel):  tutorId: str
class AccessLogEntryDTO(ApiModel): tutorId: str | None; tutorName: str
                                   action: Literal["list", "detail"]; accessedAt: str   # no entry id (ID-5)
class AccessLogPageDTO(ApiModel): items: list[AccessLogEntryDTO]; nextCursor: str | None
class TutoringSettingsDTO(ApiModel): outcomeStatsOptOut: bool; outcomePrefChangedAt: str | None
                                     safetyNoticeAcknowledgedAt: str | None
class TutoringSettingsUpdateDTO(ApiModel): outcomeStatsOptOut: bool
class ClassAccessItemDTO(ApiModel): classId: str; className: str; teacherName: str
                                    schoolName: str | None; leavable: bool       # leavable == school-less
                                    teacherIsYourTutor: bool   # class teacher holds a tutor profile with which
                                                               # the caller has a booking or a grant (XT-2)
class ClassAccessDTO(ApiModel):  items: list[ClassAccessItemDTO]
class EvidenceDTO(ApiModel):     evidenceId: str; filename: str; contentType: str; sizeBytes: int
                                 description: str | None; uploadedAt: str
class TutorProfileCreateDTO(ApiModel): publicFirstName: str; publicLastInitial: str | None = None
                                       headline: str; bio: str = ""; qualificationNote: str | None = None
                                       subjectCodes: list[str]  # 1..10
                                       offersVirtual: bool; offersInPerson: bool; offersOther: bool
                                       otherModeNote: str | None = None; areaCode: str
class TutorProfileUpdateDTO(ApiModel): # every field of Create, optional, plus:
                                       paused: bool | None = None
                                       indexable: bool | None = None   # row 17; not moderated
class TutorOwnProfileDTO(TutorProfileDTO): listingState: Literal["draft", "pending_review", "listed",
                                                                 "rejected", "suspended", "closed"]
                                           paused: bool; indexable: bool; submittedAt: str | None
                                           reviewNote: str | None; evidence: list[EvidenceDTO]
                                           reReviewRequired: bool = False
class AvailabilityReplaceDTO(ApiModel): rules: list[AvailabilityRuleDTO]
class TutorStudentItemDTO(ApiModel): studentId: str; displayName: str; grantId: str; grantedAt: str
                                     upcomingSessions: int
class TutorStudentPageDTO(ApiModel): items: list[TutorStudentItemDTO]; nextCursor: str | None
class TutorStudentDetailDTO(ApiModel): detail: StudentDetailDTO   # schemas_analytics.py, tutor projection (§e.2)
                                       grantId: str; grantedAt: str; accessRecordedAt: str
class ReportCreateDTO(ApiModel): targetType: Literal["tutor_profile", "review", "review_reply",
                                                     "booking", "booking_note"]
                                 targetId: str
                                 reason: Literal["safety_concern", "inappropriate_content", "harassment",
                                                 "spam", "fake_profile", "disputed_outcome", "other"]
                                 details: str | None = None
class ReportReceiptDTO(ApiModel): reportId: str; createdAt: str
class BlockCreateDTO(ApiModel):  tutorId: str | None = None; studentId: str | None = None  # exactly one
class BlockDTO(ApiModel):        counterpartId: str   # tutor profile id (student viewer) / student id (tutor viewer)
                                 displayName: str     # tutor public name / student_label(); never a full account name
                                 createdAt: str
class BlocksDTO(ApiModel):       items: list[BlockDTO]
```

Admin DTOs (`schemas_tutoring_admin.py`): `AdminTutorItemDTO`, `AdminTutorPageDTO` (+ `emailDelivery`), `AdminEvidenceDTO` (EvidenceDTO + `signedUrl`, TTL `settings.storage.tutor_evidence_signed_url_ttl_seconds = 300`, `response-content-disposition=attachment`), `AdminApprovalEventDTO`, `AdminTutorDetailDTO` (TutorOwnProfileDTO fields + `accountEmail`, `evidence`, `history`, `openReports`), `AdminApproveDTO` (`documentsSeen: bool`, `note`), `AdminNoteDTO`, `ModerationItemDTO` (+ `revision`: the first 16 hex characters of the SHA-256 of the item text, RF-7), `ModerationPageDTO`, `ReviewModerateDTO` (`decision`, `revision`: both required; `revision` is the one A6 showed, compared with the stored text under the row lock), `ReplyModerateDTO` (`decision` only: a reply cannot be edited), `AdminReviewDTO`, `AdminReplyDTO`, `ReportItemDTO`, `ReportPageDTO`, `ReportDetailDTO` (`snapshot`, `bookingSummary`, `notes: list[NoteDTO]` with hidden bodies visible to admin), `ReportResolveDTO`. **No admin DTO contains any `StudentDetailDTO` field** (schema test, ADR-T03).

**Viewer-dependent serialisation** (one builder per DTO, taking the viewer; tested per viewer): `BookingDTO.review`/`reviewOpensAt` student only; `studentShared` tutor only; `meetingLink`/`locationDetail` after accept to student, tutor, linked parents; system `cancelReason` → "Cancelled" for tutors; `GrantDTO.alsoTeachesClasses` student only.

### b.4 Side effects: inbox, email, audit

**Decision (F3, SC-5, EM-2).** D5.9 §1 is binding: "the notify call sits at
the router layer after the action has committed" (`BUILD/DECISIONS.md` D5.9;
`lemely/web/notify.py` makes `notify_safely` the single caller of
`NotificationService.create`, which opens its own session,
`lemely/db/notification_repo.py:292-361`). So:

1. **Email outbox rows are written inside the state-change transaction** (`email_outbox_repo.enqueue_in_session(session, …)`, `ON CONFLICT (dedupe_key) DO NOTHING`), only for recipients whose preference for the matching type is on. They commit or roll back with the change: no false notice, no lost notice.
2. **Inbox rows and push are written after commit** through `notify_safely`, from `lemely/web/tutoring_notify.py`. A failure is logged at exception level (seam, recipient id) and never fails the action (D5.9 §1). Push is payload-less (D5.10), so no note or name ever leaves the platform through push.
3. **Audit rows** (`tutor_access_audit`, `tutoring_admin_access`, `parent_link_events`) are written inside the transaction that does the read or the change; an audit failure fails the request.
4. The parent's durable record of a grant or booking is not the notification: PA1/PA2 (bookings) and PA6/PA7 (grants and the access log, row 16 i) show the facts. That keeps D5.9 §2's rule true ("no notification is the sole record of anything"). The one exception is the unlink notice, whose subject (the link) is gone afterwards; its durable record is `parent_link_events`.

The sentence in the previous revision ("written in the same transaction as the state change … `NotificationService.create` already gates") was false and is withdrawn.

| Event | Inbox type → recipients (after commit) | Inbox `dedupe_key` | Email template (outbox, in transaction) → recipients | Outbox `dedupe_key` |
|---|---|---|---|---|
| Booking requested | `booking_request` → tutor; `booking_update` → linked parents (and the student, if a parent requested) | `booking:{booking_id}:requested` | `booking_requested` → tutor; `booking_requested_family` → linked parents | `booking:{booking_id}:requested:{recipient_id}` |
| Accepted / declined | `booking_update` → student, linked parents | `booking:{booking_id}:{event}` | `booking_accepted` / `booking_declined` → student, linked parents | `booking:{booking_id}:{event}:{recipient_id}` |
| Cancelled (incl. a tutor's late cancel, row 18) | `booking_update` → every other party + linked parents | `booking:{booking_id}:cancelled` | `booking_cancelled` → same | as above |
| Completed / no-show | `booking_update` → student, linked parents (tutor if the student or parent completed) | `booking:{booking_id}:{event}` | none | — |
| New note | `booking_note` → the other participant | `note:{note_id}` | none (email never carries notes) | — |
| New **tutor-authored** note | `booking_note` → every linked parent, at most one per booking per tutor-zone day (SC-9) | `note-day:{booking_id}:{yyyy-mm-dd}` | none | — |
| Grant created | `tutor_access` → tutor, linked parents | `grant:{grant_id}:created` | `tutor_access_granted` → linked parents | `grant:{grant_id}:created:{recipient_id}` |
| Grant revoked / ended (block, suspension, close) | `tutor_access` → tutor (generic "access ended" copy, SC-11); student when ended by suspension/close | `grant:{grant_id}:ended` | none | — |
| Review text moderated; reply moderated | `tutor_review` → author student / tutor | `review:{review_id}:{event}:{revision}` / `reply:{reply_id}:{event}:{revision}` | none | — |
| (no "new review" notice to tutors: timing would identify the reviewer, SC-12) | | | | |
| Listing approved / rejected / suspended / reinstated / closed | `tutor_listing` → tutor | `listing:{approval_event_id}` | `tutor_listing_decision` → tutor | `listing:{approval_event_id}` |
| Parent link removed (existing route, SC-1) | `parent_link` → the unlinked parent | `parent-link:{event_id}` | `parent_unlinked` → that parent | `parent-link:{event_id}:{recipient_id}` |
| Parent link added (existing routes, SC-1) | `parent_link` → every parent already linked | `parent-link:{event_id}` | `parent_linked` → those parents | as above |
| Student joins a school-less class whose teacher holds a tutor profile (existing routes, SC-2d) | `tutor_access` → the student's linked parents | `class-join:{enrollment_id}` | `class_joined_tutor` → linked parents | `class-join:{enrollment_id}:{recipient_id}` |
| `safety_concern` report filed | `tutoring_report` → every `platform_admin` (SC-10) | `report:{report_id}` | none | — |

**Listing decision copy (T10 review).** The `tutor_listing_decision` context is `approval_event_id`, `decision` and `listed`; `listed` says whether the profile is listed once the decision has applied, and the inbox builder takes the same flag. Only `reinstated` takes either value: `approved` is always listed, and `rejected`, `suspended` and `closed` never are; any other pair is refused, because its copy would be false. A reinstatement to `listed` is titled "Your tutor profile is listed again"; one to `pending_review` is titled "Your tutor profile is back in review" (the inbox title and the first sentence of the email alike).

**Copy rules (SC-9, CS-9).** Every title and body is fixed copy with names only, e.g. "New note on your session with Sara M."; never note text, a reason, a link or a place. A tutor's late cancel (row 18) uses its own fixed line, "Sara M. cancelled your session. Open it to see why.", and the reason itself is read only in the booking (S-37, P-06), never in a notice or an email. Payloads hold ids only. `["notifications"]` is on the react-query persist allowlist (`web/src/lib/offline/persistAllowlist.ts:20-28`), so fixed copy is what keeps safeguarding text off devices. No tutor-facing notification or DTO reveals whether a student has linked parents.

**Email delivery (F4, F28, SC-6, SC-15, SC-25).** There is no request-time send and no FastAPI `BackgroundTask`: on Cloud Run (`--min-instances=0`, CPU throttled outside requests, `.github/workflows/deploy.yml:313`) post-response work may never get CPU. Instead `lemely/web/tutoring_email.py::deliver_tutoring_email` is **one more job on the existing sweeper** (`Sweeper.sweep_once`, `lemely/web/scheduled_notifications.py`; started by `lemely/web/app.py:63-90`; every 60 s by default, `NotificationsSettings.sweep_poll_seconds`; disabled under test, where tests call the job directly). Per tick it handles at most 20 rows, each in its own transaction: `SELECT … WHERE status = 'pending' ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED` (safe across replicas); resolve the recipient (`skipped` if the address is a parent placeholder `_PLACEHOLDER_EMAIL_DOMAIN` (`parent_repo.py:96`), `email_verified_at` is NULL, or the recipient has switched the template's notification type off since the row was written, `preference_off`; the preference is read again at send time; then, for a provider that really delivers, `skipped` when the 24 h sent count ≥ `[tutoring] email_daily_cap` (default 60, below Resend's 100/day free quota shared with account mail, F28), counted under a transaction-scoped `pg_advisory_xact_lock` so that replicas cannot both read the same count and overshoot); send; mark `sent` or `failed`, `attempts = 1` (a `skipped` row keeps `attempts = 0`). **First attempt only: a `failed` row is never retried (row 12).** A crash between send and commit rolls the row back to `pending`, so a rare duplicate is possible; a row can also stay `pending` while no instance is serving traffic (both documented in DELIVERY §5.7).
Provider: `TransactionalEmailProvider.send(to, template, context)` (new protocol, `lemely/io/notify_email.py`). `ResendTransactionalEmailProvider` reuses `[email]` (`api_key`, sender, `app_base_url`) and the existing `ResendEmailProvider`'s HTTP shape (`lemely/auth/email.py:240`); `MockTransactionalEmailProvider` is used when `[email] api_key` is unset and marks rows **`skipped` with `last_error='mock_provider'`, never `sent`**, logging only the outbox id and template. `lemely doctor` and app startup log a WARNING when tutoring routes are mounted with the mock; X-04 shows "Email delivery: mock". Links are built only as `urljoin(settings.email.app_base_url, fixed_path(id))`; templates are fixed and HTML-escaped; `last_error` never contains an address (the provider's `ExternalServiceError` text includes the recipient, `email.py:359-369`, so it is scrubbed).

**Quotas (SC-15), all DB-backed COUNTs over existing indexes, no process state:** booking creations ≤ 10 per requester per 24 h; cancellations ≤ 10 per canceller per 24 h; reports ≤ 20 per reporter per 24 h.

### b.5 Caching, robots and edge rules (SC-18, SC-26, PP-7)
- `Cache-Control: private, no-store` on every **NS** route above (T19, T20, notes, every `BookingDTO`/`GrantDTO`/`AccessLogPageDTO`/`ClassAccessDTO` response, A10). Since PLAN rev 2 (P12) this means every non-PUBLIC tutoring route on every status, set once by a shared route class rather than per handler; P1–P3 alone send `public`. A vitest asserts no tutoring query key is on `persistAllowlist.ts` (F32).
- `public, max-age=60` only on P1–P3. The worker (`web/worker/index.ts`, which proxies `/api/*` with plain `fetch()`) adds a `caches.default` read-through for `GET /api/public/tutors*` and `/api/public/tutoring-areas` only, keyed on the full URL, 60 s. This shields Postgres from repeated identical requests; it is not a rate limit. A Cloudflare WAF rate-limit rule on `/api/public/*` is the rate limit, documented in `docs/deployment.md` as an ops step **if the plan offers one (not verified, §h)**.
- **Search indexing of tutor pages (row 17: the public card is indexable by default, per-tutor opt-out, honoured by a worker lookup).** What exists today (read 2026-10-25): production and staging serve the SPA from Workers Static Assets (`web/wrangler.jsonc`: `not_found_handling: "single-page-application"`, `run_worker_first: ["/api/*"]`, binding `ASSETS`); `web/worker/index.ts` handles `/api/*` only and sets the five security headers itself; `web/public/_headers` has one `/*` block with those five headers; `web/public/robots.txt` disallows `/api/`, `/student`, `/teacher`, `/parent`, `/admin`, `/settings`, `/join` and not `/tutors`; `web/nginx.conf` is the Docker/self-host deploy. Cloudflare's docs state that `_headers` rules are **not** applied to responses generated by Worker code when `run_worker_first` matches, so every header on a worker-served path must be set by the worker.
  - **Route.** `web/wrangler.jsonc` `run_worker_first` becomes `["/api/*", "/tutors", "/tutors/*"]`. `web/worker/index.ts` dispatches `/tutors` and `/tutors/*` to `handleTutorPage(request, env)` in a new module `web/worker/robots.ts`; `/api/*` behaviour is unchanged. `Env` gains `ASSETS: Fetcher`.
  - **Directory `/tutors`:** serve `env.ASSETS.fetch(request)` with `X-Robots-Tag: noindex, follow`. The directory lists every listed tutor, opted-out ones included, so it is never indexed; `follow` lets crawlers reach the cards.
  - **Card `/tutors/{id}`** (exactly one segment matching the lowercase-or-uppercase UUID pattern): look up `GET {BACKEND_URL}/api/public/tutors/{id}` with a request built from scratch (method GET, no cookie, no `Authorization`, no client headers), through the same `caches.default` read-through as P1–P3 (60 s), with a 1500 ms timeout. The card is indexable **only if** the lookup returns 200 and its JSON has `indexable === true`; then the response carries **no** `X-Robots-Tag`. Every other outcome sends `X-Robots-Tag: noindex, nofollow`: opted out, 404 (unknown, unlisted, paused, suspended, closed — P2's one predicate), any other status, network error, timeout, unparseable JSON, a missing or non-boolean field. A path under `/tutors/` that is not one UUID segment gets `noindex, nofollow` **without** calling the backend. Fail closed in every case.
  - **Body and headers.** The body is always `env.ASSETS.fetch(request)` (the SPA shell through `not_found_handling`); the worker never builds HTML. It sets the five security headers through the same helper the `/api/*` path uses (`headerParity.test.ts` is extended to that helper), and leaves `Cache-Control` as Static Assets returns it.
  - **What the lookup cannot do.** It requests one fixed path template on the backend, so it is not an open proxy; it forwards nothing from the client; it reads one boolean. Cost: at most one backend request per uncached card view; the WAF rule below is still the rate limit.
  - **Opt-out timing.** An opt-out reaches the edge within 60 s (cache TTL). A search engine drops an already-indexed card only when it next crawls it; T-16 says so.
  - **`web/public/_headers`** gets **no** `/tutors` rule: if the platform applied one to `ASSETS.fetch` responses it would mark every card `noindex` and silently defeat row 17. A test asserts the rule is absent.
  - **nginx (`web/nginx.conf`, Docker/self-host only, not production):** no per-tutor lookup. Every `/tutors*` page stays `noindex, nofollow`: `map $request_uri $robots_tag { ~^/tutors(/|$) "noindex, nofollow"; default ""; }` and `add_header X-Robots-Tag $robots_tag always;` **inside `location = /index.html`**, which the SPA fallback reaches by internal redirect, repeating that block's existing security headers (a location with its own `add_header` stops inheriting). Documented as a limit of the self-host deploy.
  - **Client meta (defence in depth, for crawlers that render JavaScript):** G-16 renders `<meta name="robots" content="noindex, follow">`; G-17 renders `noindex, nofollow` unless P2 returned `indexable: true`, and while P2 is loading or failed.
  - **`robots.txt`** never disallows `/tutors` (a disallowed page's header is never read).
  - **Discovery:** no sitemap in v1 (§i).
  - **Tests:** `web/tests/unit/workerTutorRobots.test.ts` (node environment, `ASSETS`, `fetch` and `caches` stubbed; names in §e.4); `web/tests/unit/headerParity.test.ts` extended; `tests/test_deploy_headers.py` parses `nginx.conf`, `robots.txt` and `_headers`. **Deploy checklist** (staging, after the first deploy with the worker change): `curl -sI https://staging.lemelyig.com/tutors` shows `noindex, follow`; a seeded indexable tutor's card shows no `X-Robots-Tag` and `content-type: text/html`; an opted-out tutor's card and `/tutors/not-a-uuid` show `noindex, nofollow`.

---

## c. Authorization

### c.1 `EXPECTED` rows for `tests/test_authz_matrix_complete.py`

New module-level guard constants (the section-count test looks each heading name up in `globals()`; before adding them, confirm no existing constant has the same member set, or merge into that section):

```python
STUDENT_OR_PARENT = frozenset({"student", "parent"})
STUDENT_OR_TEACHER = frozenset({"student", "teacher"})
TUTORING_PARTY = frozenset({"student", "parent", "teacher"})
```

Headings must match `#\s*─+\s*([A-Z_]+)\s*\((\d+)\)` (`test_authz_matrix_complete.py:578`) and carry the count of the rows present in the section, which the section-count test checks on every run; the counts below are the **final** ones, reached when the last route lands (F23; build order in `BUILD/tutoring/PLAN.md` §3). Counts below are against `314ef8ec`; re-derive after the wave-0 merge of `origin/develop`. Each guard has exactly one heading, whose count is that guard's **total** row count in the file (existing plus tutoring rows); adding a tutoring row updates that one heading and never adds a second heading for the same guard (`test_the_section_counts_in_this_file_match_what_it_registers`).

```python
    # ── PUBLIC (15) ──  (+3) rows 5a/5b: minimal card only, no availability filter.
    ("GET", "/api/public/tutors"): PUBLIC,
    ("GET", "/api/public/tutors/{tutor_id}"): PUBLIC,
    ("GET", "/api/public/tutoring-areas"): PUBLIC,
    # ── STUDENT_OR_PARENT (6) ── row 10: parents browse and book for a linked child.
    ("GET", "/api/tutors"): STUDENT_OR_PARENT,
    ("GET", "/api/tutors/{tutor_id}"): STUDENT_OR_PARENT,
    ("GET", "/api/tutors/{tutor_id}/reviews"): STUDENT_OR_PARENT,
    ("GET", "/api/tutors/{tutor_id}/outcomes"): STUDENT_OR_PARENT,
    ("GET", "/api/tutors/{tutor_id}/slots"): STUDENT_OR_PARENT,
    ("POST", "/api/bookings"): STUDENT_OR_PARENT,
    # ── STUDENT (80) ──  (+17)
    ("GET", "/api/student/bookings"): STUDENT,
    ("GET", "/api/student/bookings/{booking_id}"): STUDENT,
    ("POST", "/api/student/bookings/{booking_id}/cancel"): STUDENT,
    ("GET", "/api/student/bookings/{booking_id}/notes"): STUDENT,
    ("POST", "/api/student/bookings/{booking_id}/notes"): STUDENT,
    ("POST", "/api/student/bookings/{booking_id}/review"): STUDENT,
    ("POST", "/api/student/bookings/{booking_id}/complete"): STUDENT,
    ("PATCH", "/api/student/reviews/{review_id}"): STUDENT,
    ("GET", "/api/student/tutor-grants"): STUDENT,
    ("POST", "/api/student/tutor-grants"): STUDENT,
    ("POST", "/api/student/tutor-grants/{grant_id}/revoke"): STUDENT,
    ("GET", "/api/student/tutor-access-log"): STUDENT,
    ("GET", "/api/student/tutor-access/classes"): STUDENT,
    ("GET", "/api/student/tutoring-settings"): STUDENT,
    ("PUT", "/api/student/tutoring-settings"): STUDENT,
    ("POST", "/api/student/tutoring-safety-notice"): STUDENT,
    # SC-2c: leave a school-less class. New route on the existing student_classes router.
    ("DELETE", "/api/student/classes/{class_id}"): STUDENT,
    # ── TEACHER (24) ──  (+21) ADR-T01: role half only; "owns a tutor profile" is
    # object-level (tests/test_web_tutoring_authz.py), invisible to this sweep.
    ("GET", "/api/tutor/profile"): TEACHER,
    ("POST", "/api/tutor/profile"): TEACHER,
    ("PATCH", "/api/tutor/profile"): TEACHER,
    ("POST", "/api/tutor/profile/submit"): TEACHER,
    ("PUT", "/api/tutor/profile/availability"): TEACHER,
    ("POST", "/api/tutor/profile/evidence"): TEACHER,
    ("DELETE", "/api/tutor/profile/evidence/{evidence_id}"): TEACHER,
    ("GET", "/api/tutor/profile/preview"): TEACHER,
    ("GET", "/api/tutor/bookings"): TEACHER,
    ("GET", "/api/tutor/bookings/{booking_id}"): TEACHER,
    ("POST", "/api/tutor/bookings/{booking_id}/accept"): TEACHER,
    ("POST", "/api/tutor/bookings/{booking_id}/decline"): TEACHER,
    ("POST", "/api/tutor/bookings/{booking_id}/cancel"): TEACHER,
    ("POST", "/api/tutor/bookings/{booking_id}/complete"): TEACHER,
    ("POST", "/api/tutor/bookings/{booking_id}/no-show"): TEACHER,
    ("GET", "/api/tutor/bookings/{booking_id}/notes"): TEACHER,
    ("POST", "/api/tutor/bookings/{booking_id}/notes"): TEACHER,
    ("POST", "/api/tutor/reviews/{review_id}/reply"): TEACHER,
    ("GET", "/api/tutor/reviews"): TEACHER,
    ("GET", "/api/tutor/students"): TEACHER,
    # Grant-gated and audit-logged on every read (ADR-T02); school_admin and
    # platform_admin denied by guard: there is no admin path to granted data.
    ("GET", "/api/tutor/students/{student_id}"): TEACHER,
    # ── PARENT (11) ──  (+7) new routes; the four existing parent routes are unchanged.
    ("GET", "/api/parent/children/{child_id}/bookings"): PARENT,
    ("GET", "/api/parent/children/{child_id}/bookings/{booking_id}"): PARENT,
    ("GET", "/api/parent/children/{child_id}/bookings/{booking_id}/notes"): PARENT,
    ("POST", "/api/parent/children/{child_id}/bookings/{booking_id}/cancel"): PARENT,
    ("POST", "/api/parent/children/{child_id}/bookings/{booking_id}/complete"): PARENT,
    # Row 16 (i): read-only view of the child's grants and tutor-read log.
    ("GET", "/api/parent/children/{child_id}/tutor-grants"): PARENT,
    ("GET", "/api/parent/children/{child_id}/tutor-access-log"): PARENT,
    # ── TUTORING_PARTY (1) ──
    ("POST", "/api/tutoring/reports"): TUTORING_PARTY,
    # ── STUDENT_OR_TEACHER (3) ──
    ("GET", "/api/tutoring/blocks"): STUDENT_OR_TEACHER,
    ("POST", "/api/tutoring/blocks"): STUDENT_OR_TEACHER,
    ("DELETE", "/api/tutoring/blocks/{counterpart_id}"): STUDENT_OR_TEACHER,
    # ── PLATFORM_ADMIN (21) ──  (+12)
    ("GET", "/api/admin/tutors"): PLATFORM_ADMIN,
    ("GET", "/api/admin/tutors/{tutor_id}"): PLATFORM_ADMIN,
    ("POST", "/api/admin/tutors/{tutor_id}/approve"): PLATFORM_ADMIN,
    ("POST", "/api/admin/tutors/{tutor_id}/reject"): PLATFORM_ADMIN,
    ("POST", "/api/admin/tutors/{tutor_id}/suspend"): PLATFORM_ADMIN,
    ("POST", "/api/admin/tutors/{tutor_id}/close"): PLATFORM_ADMIN,
    ("GET", "/api/admin/tutoring/moderation"): PLATFORM_ADMIN,
    ("POST", "/api/admin/tutoring/reviews/{review_id}/moderate"): PLATFORM_ADMIN,
    ("POST", "/api/admin/tutoring/replies/{reply_id}/moderate"): PLATFORM_ADMIN,
    ("GET", "/api/admin/tutoring/reports"): PLATFORM_ADMIN,
    ("GET", "/api/admin/tutoring/reports/{report_id}"): PLATFORM_ADMIN,
    ("POST", "/api/admin/tutoring/reports/{report_id}/resolve"): PLATFORM_ADMIN,
```

Other edits to the same file: `len(_NON_PUBLIC) == len(ROUTES) - 15` (was 12; the comment names the three public tutoring routes); add the three new guard sets to the `_REPRESENTATIVE` guard tuple (`:514-517`) and assert `len(_REPRESENTATIVE) == 9`. All new path params are UUIDs, so `_PLACEHOLDERS` needs no change. The existing rows for the routes in §c.4 are **not edited**.

### c.2 Denials per guard (what the generated sweep proves)

| Guard | Routes | 401 unauthenticated | 403 roles | New 403 cases |
|---|---|---|---|---|
| PUBLIC | 3 | — | — | 0 |
| STUDENT_OR_PARENT | 6 | 6 | teacher, school_admin, platform_admin | 18 |
| STUDENT | 17 | 17 | parent, teacher, school_admin, platform_admin | 68 |
| TEACHER | 21 | 21 | student, parent, school_admin, platform_admin | 84 |
| PARENT | 7 | 7 | student, teacher, school_admin, platform_admin | 28 |
| TUTORING_PARTY | 1 | 1 | school_admin, platform_admin | 2 |
| STUDENT_OR_TEACHER | 3 | 3 | parent, school_admin, platform_admin | 9 |
| PLATFORM_ADMIN | 12 | 12 | student, parent, teacher, school_admin | 48 |
| **Total** | **70** | **67** | | **257** |

### c.3 Object-level rules (IDOR defences; DB-backed tests in `tests/test_web_tutoring_authz.py` — one file name, F23)

Every rule has a passing test and at least one failing case (the check must be shown to go red).

| # | Rule | Enforced in | Failure |
|---|---|---|---|
| O1 | Tutor routes act only on the caller's own profile, resolved from `auth.user_id`; no tutor route takes a tutor id | `TutorProfileRepository.for_user` | 404 `no_tutor_profile` |
| O2 | A tutor reads a student **only** with a currently valid grant (`grant_status == "active"`), checked per request; the roster is never consulted | `TutorGrantRepository.require_valid_grant` | 403 `access_ended` if a grant row existed for this pair; 404 otherwise |
| O3 | Every successful T19/T20 read writes its audit rows before data is loaded, in the validity-check transaction; failure aborts the response | same transaction | 500, no body |
| O4 | Tutor booking/note/reply routes require `booking.tutor_profile_id` / `review.tutor_profile_id` = caller's profile | repository `WHERE` | 404 |
| O5 | Student routes require `booking.student_id` / `review.student_id` / `grant.student_id` = `auth.user_id` | repository `WHERE` | 404 |
| O6 | SP6: a student's `studentId` absent or equal to `auth.user_id`; a parent's `studentId` required and linked at request time (link row locked `FOR SHARE`, §a.4b) | service | 403 `not_self` / `not_linked`; 404 unknown child |
| O7 | Parent routes (PA1–PA7): `child_id` linked to the caller, checked on every call through `ParentLinkService.get_child` (never a direct join, F32), then `booking.student_id = child_id` | service | 403 not linked; 404 booking |
| O8 | Parent cancel (PA4) and complete (PA5) only if `booking.requested_by_user_id = auth.user_id AND requested_by_party = 'parent'` | service | 403 `not_requester` |
| O9 | Notes: post only as the booking's student or tutor while `can_post_note` holds; parents read only | service + `ck_tutor_booking_notes_author_party` | 404 / 409 `notes_closed` |
| O10 | Reviews: only that booking's student, only when `completed` and `now >= ends_at + 7 d`, account ≥ 14 days; one per booking (DB); parents cannot review (guard) | service + `uq_tutor_reviews_booking_id` | 404 / 409 |
| O11 | Directory, profile, reviews, outcomes, slots, booking create, grant create: tutor listed and not paused (404 to students/parents otherwise); pairs in an active block hidden | repository predicates | 404 / 409 |
| O12 | Reports: the reporter must see the target. Booking and note: a party (student, tutor, linked parent of the student). Tutor profile: any party to **any** booking with that tutor, in **any** listing state (SC-10), or any student/parent while listed. Review/reply: any student or parent while the tutor is listed; the tutor for reviews of themself | service | 404 |
| O13 | Blocks: a student may block only a tutor profile (by `tutorId`); a tutor may block only a student who has booked or granted them (by `studentId`) | service | 404 |
| O14 | Cross-gate, no union: a class teacher without a grant is 404 on T20; a tutor with a grant but no roster entry stays 403 on `GET /api/teacher/students/{id}` (`teacher_student_detail`, `teacher.py:2380`) | separate gates | as stated |
| O15 | `platform_admin`: no route returns granted analytics; notes reachable only through A10 for a report targeting that note or booking, and each view is logged (SC-23) | route set + schema test | — |
| O16 | `meeting_link`/`location_detail` serialised only when `state ∈ {accepted, completed, no_show}` and the viewer is the student, the tutor or a linked parent | DTO builder | `null` |
| O17 | Evidence files: never served to non-admins; admin gets 300 s attachment URLs on A2 only, each logged | DTO builder | — |
| O18 | The grant lookup is keyed on `for_user(auth.user_id).id`; the repository method takes no other profile id. Tutor B with a booking with student X gets 404 on T20 even if X granted tutor A (SC-27, ID-1) | `require_valid_grant(caller_profile, student_id)` signature | 404 |
| O19 | Report-target visibility is resolved server-side from the target's own parent rows (note → booking → participants; reply → review → tutor; review → booking); a client-supplied booking id is never trusted | service | 404 |
| O20 | Evidence list/delete scoped `WHERE tutor_profile_id = :caller_profile` | repository | 404 |
| O21 | Cursors carry sort-key values only, tagged with their endpoint, decoded with types, bound as parameters; a cursor from another endpoint → 422 | `core.keyset` + router | 422 |
| O22 | PA6/PA7 return exactly the child's own grants and log; never another child's; never write a `tutor_access_audit` row | service | 403 / 404 |
| O23 | S14/PA5: only the booking's student or requesting parent, only `awaiting_outcome` for ≥ 48 h with no tutor outcome | service + CAS | 409 `outcome_claim_not_open` |
| O24 | S17: deletes only the caller's own enrolment, only for `school_id IS NULL` | `ClassService.leave_school_less_class(student_id, class_id)` | 404 |
| O25 | S16 lists only classes the caller is enrolled in | repository | — |
| O26 | Safety notice: a student-requested SP6 and a student's S5 require `safety_notice_acknowledged_at`; parent-requested bookings do not (the child sees it before their first note) | service | 409 `safety_notice_required` |
| O27 | T21 returns only reviews of the caller's profile; review text only when approved | repository | — |
| O28 | B3 resolves `counterpart_id` by the caller's role (tutor profile id for students, student id for tutors) and only within the caller's own block rows | service | 404 |
| O29 | No PUBLIC, STUDENT, PARENT or STUDENT_OR_PARENT DTO contains a tutor's `users.id`; no tutoring DTO contains any `users.email` value; no tutor-facing DTO reveals parent-link presence | schema tests | — |
| O30 | Late cancel (row 18): inside 24 h of the start only the booking's tutor may cancel an accepted booking, and only with a non-blank reason; the student (S3) and the requesting parent (PA4) are refused | `core.booking.check_transition` + CAS `WHERE` + `ck_tutor_bookings_late_cancel_reason` | 409 `cancel_window_closed` (S3, PA4); 422 `reason_required` (T13) |
| O31 | `indexable` is served only by P2 (`PublicTutorCardDTO`), the tutor's own `TutorOwnProfileDTO` and the admin detail (A2); no other DTO carries it, and P2 still returns 404 for every tutor that is not listed-and-not-paused, so the worker lookup learns nothing a public visitor cannot | schema test + P2 predicate | 404 |

### c.4 Existing routes whose behaviour changes (row 14: SC-1, SC-2) — no permission change

Guards, object rules and response bodies of these routes are unchanged; the authz-matrix rows for them are not edited, so `test_authz_matrix_complete.py` (declared guard = wired guard, 401/403 sweeps) proves the guard half. What changes is listed exhaustively:

| Route (guard, unchanged) | Before | After |
|---|---|---|
| `DELETE /api/student/parent-links/{parent_id}` (STUDENT; `student.py:1375-1389`) | Deletes the link; nobody told; no history | Same delete, plus in the same transaction a `parent_link_events(unlinked)` row and a `parent_unlinked` outbox row for the unlinked parent; after commit a `parent_link` inbox notice to that parent. A no-op unlink writes nothing. `ParentLinkService.unlink` returns `bool` (removed or not) instead of `None`; its only caller is this route |
| `POST /api/invites/{code}/redeem` (AUTH_ANY; `invites.py:128`) — parent-invite branch | Links any parent holding the code; no limit on redeemed links | **New 409 `parent_limit`** when the child already has 4 linked parents and the caller is not one of them (cap enforced in `ParentLinkService.link_in_session` under `SELECT … FROM users WHERE id = :child FOR UPDATE`; re-linking an already-linked pair stays idempotent). On a new link: `parent_link_events(linked)`, `parent_linked` outbox rows to every previously linked parent (in transaction), `parent_link` inbox notices after commit. Children who already have more than 4 links keep them |
| `POST /api/invites/{code}/redeem` — class branch (bare `classes.join_code` or class invite) | Enrols the caller | Same enrolment; if newly enrolled in a class with `school_id IS NULL` whose `teacher_id` owns a tutor profile, a `class_joined_tutor` outbox row and a `tutor_access` inbox notice go to the student's linked parents |
| `POST /api/student/classes/join` (STUDENT; `student.py:1320`) | Enrols the caller | As the class branch above |
| `POST /api/auth/parent/signup` (PUBLIC; `auth.py:413`) | Creates the parent account, then redeems the invite; a redeem failure is logged and swallowed (`auth.py:475-482`) | The pre-check `_require_live_parent_invite` also returns **409 `parent_limit`** before any account is created when the child is at the cap; the redeem itself behaves as above |
| `GET /api/teacher/students/{id}`, `GET /api/classes/{class_id}/roster` and other roster reads | — | Unchanged code. They return fewer students after a block, suspension, close or S17 removed a school-less enrolment: a data effect, not a permission change |

New behaviour enters only through `ParentLinkService.link_in_session`/`unlink` (the single `parent_child_links` query, `parent_repo.py:192-224`), a new `ClassService.join_by_code_outcome()` returning `(ClassRow, newly_enrolled)` (the old `join_by_code` keeps its signature, `class_repo.py:456`), and the after-commit notify calls in the four handlers. Hot files touched: `lemely/db/parent_repo.py`, `lemely/db/invite_repo.py` (`_redeem_parent_invite`, `:783`), `lemely/db/class_repo.py`, `lemely/web/routers/{student,invites,auth,student_classes}.py`; owner: PLAN task T09. Everything in this section ships in wave 2 (with the outbox it writes to, and before any booking or grant exists), including S16 and S17; their screen section (S-38 part 3) lands with S-38 in wave 4. Two sweeps arrive with their features: the grant half of the suspension sweep in wave 4, the block sweep in wave 5.

Tests (`tests/test_parent_link_integrity.py`, `tests/test_class_side_door.py`; each with a red case):
- `test_unlink_notifies_unlinked_parent_inbox_and_outbox` · `test_unlink_noop_writes_no_event_and_no_notice` · `test_unlink_writes_link_event`
- `test_redeem_notifies_existing_parents` · `test_redeem_cap_409_parent_limit_at_four` · `test_redeem_relink_at_cap_is_idempotent_200` · `test_existing_children_over_cap_keep_links`
- `test_parent_signup_at_cap_409_creates_no_user`
- `test_race_two_redeems_at_three_links_exactly_one_succeeds` (`tests/test_concurrency.py`)
- `test_join_school_less_class_of_tutor_notifies_parents` (both join routes) · `test_join_school_class_or_non_tutor_teacher_no_notice` · `test_rejoin_is_idempotent_no_second_notice`
- `test_leave_school_less_class_204_then_404` · `test_leave_school_class_404` · `test_leave_class_not_enrolled_404`
- `test_block_removes_school_less_enrolment_keeps_school_enrolment` · `test_suspension_removes_school_less_enrolments_of_tutoring_students_only` · `test_close_removes_school_less_enrolments`
- `test_existing_route_guards_unchanged` (asserts the `EXPECTED` rows for the five routes above equal their values at `314ef8ec`)

---

## d. Screens

Numbers continue each portal's sequence in `docs/LEMELY_UI_SPEC.md` Part 3
(last used: G-15, S-31, T-12, P-04, X-03) **and skip the provisional IDs
already used by `web/scripts/audit.mjs`: `S-32-provisional` (`/student/parents`),
`T-13-provisional` (`/teacher/grading`), `T-14-provisional`** (F21). Student
screens therefore start at S-33 and teacher screens at T-15. Add these rows to
Part 3 and these sections to Part 4 when the feature ships.

**Rules for every screen below.**
- *Loading:* skeleton rows shaped like the content (no bare spinner); C-10 is reserved for marking.
- *Error:* C-11 `ErrorState` with the specific failure and a retry; `warn` tone by default.
- *Offline:* C-11 `OfflineState`; booking actions disabled with the reason.
- *Times:* "Thu 30 Oct · 17:00–18:00 Cairo time" (zone label from `zoneLabel`).
- *Layout:* no horizontal scroll at 320px; touch targets ≥ 44px **(a design rule, not measured by any gate; DELIVERY §5.5 records existing 31px `size="sm"` controls, F22)**; design tokens only; English copy through `check_copy.mjs` plus the new tutoring rule banning "improvement" and "verified" in tutoring copy files (F22).
- *Ratings:* C-22 everywhere; "New" below 3 students, never stars.
- *Free text:* rendered as plain text, never auto-linked; a 422 `contact_details_not_allowed` shows "To keep everyone safe, keep contact details off Lemely. Use the session notes instead."

### New components (add to `docs/COMPONENT_CATALOGUE.md`)
| ID | File | What |
|---|---|---|
| C-17 | `ordinal-distribution.tsx` | Horizontal stacked bar over an ordered ladder (A*, A, B, C, D, E, U), segments coloured by `gradeBand(grade)` from C-1, every non-zero segment labelled (labels move outside narrow segments), zero rungs listed with 0, `n` caption, "Show as table" toggle rendering a real `<table>` with caption. Pure SVG |
| C-18 | `grade-change-summary.tsx` | Three-part bar "Lower grade · Same grade · Higher grade" with icons (`ArrowDown`/`Equals`/`ArrowUp`) and counts, neutral tokens, `n` caption, table toggle. Title fixed: "Change in grade while with this tutor". The higher/same/lower reading of row 8 is approved (row 15e) |
| C-19 | `slot-picker.tsx` | Day chips (wrap) + radio group of time buttons per day; zone label; per-day empty line; arrow keys within group |
| C-20 | `booking-status.tsx` | Icon + text per effective state; never colour alone |
| C-21 | `notes-thread.tsx` | Chronological notes with author label, hidden-note placeholder ("Removed by Lemely"), per-note Report, optional composer, fixed line "Notes can be reported. Lemely staff read notes only when one is reported." Tutor composer adds, always: "This student's parents can read these notes." (SC-9). Frozen state: "Notes are paused while Lemely looks at a report." |
| C-22 | `rating-summary.tsx` | "4.6 · 12 students" (one decimal) with a star glyph, or a "New" pill; full-sentence `aria-label` (SC-16) |
| C-23 | `tutor-card.tsx` | Directory card composing C-22: public name, headline, subject chips, mode icons + labels, area |
| C-24 | `safety-notice-sheet.tsx` | The first-booking safety notice (row 16 ii), copy below; one "I understand" button that calls S15; not dismissible without it |

**C-24 copy (fixed).** Title: "Before your first session". Body:
- "Tutors on Lemely are adults you may not have met. Lemely looked at documents they uploaded. That is not a criminal-records check."
- "Keep messages on Lemely. Don't share your phone number, WhatsApp or social media, and don't move the conversation somewhere else."
- "For in-person sessions, meet somewhere public and tell a parent or another adult you trust where you will be."
- "If anything makes you uncomfortable, stop, tell an adult you trust, and use Report. You can also block the tutor."
- "If someone is in danger, call 16000 (Child Helpline, Egypt)."
Button: "I understand". Shown once per student: S-35 shows it before the request when `safetyNoticeAcknowledgedAt` is null; S-37 shows it before a student's first note if they have not seen it (a parent booked for them). The server enforces it (O26), so a client cannot skip it.

Reused: C-1, C-5, C-8 (T-20 via the T-05 composition), C-11, C-13 nav shells (student "Tutors", "Sessions"; teacher "Tutoring"; parent "Tutors"; admin "Tutors", "Moderation", "Reports"), C-14, C-15.

### Public (G)

**G-16 · Tutor directory (public)** — `/tutors`
**Contains.** Intro ("Find a tutor for IGCSE Maths, Additional Maths and Physics. Fees are agreed with the tutor, outside Lemely."). Filters: subject, mode, area (from P3), minimum rating. C-23 cards. "Load more". "Sign in to see full profiles, availability, reviews and results."
**States.** Empty: "No tutors match these filters yet." + "Clear filters". Empty platform: "Tutors are being reviewed. Check back soon."
**Exits.** G-17, G-04, G-02.

**G-17 · Tutor public card** — `/tutors/:tutorId`
**Contains.** The public fields only, larger; "Sign in to book".
**States.** Unlisted or unknown → "This tutor isn't listed." (C-11 empty, link to G-16).
**Exits.** G-04 → S-34 (student) or P-07 (parent), G-16.
Robots (§b.5, row 17): G-16 is always `noindex, follow`; G-17 has no `X-Robots-Tag` when the tutor's card is indexable (the default) and `noindex, nofollow` when they opted out or are not listed. The `<meta name="robots">` tag matches.

### Student (S)

**S-33 · Find a tutor** — `/student/tutors`
**Contains.** G-16's filters plus "Usually available" (day chips + morning/afternoon/evening). C-23 cards in rank order with an info disclosure: "Tutors with few reviews are ranked as if they also had five 4-star reviews, so one great review can't put someone at the top." (F10). Load more.
**Exits.** S-34.

**S-34 · Tutor profile** — `/student/tutors/:tutorId`
**Contains.** Header: public name, headline, C-22, subjects, modes, area, "Listed since {Mon YYYY}", "Documents seen by Lemely" when `documentsSeen` (disclosure: "A Lemely admin looked at documents this tutor uploaded. This is not a background check."). Bio, qualification note, other-mode note. Weekly availability table (zone label). **Results section (ADR-T04)** per subject: C-17 and C-18 side by side (stacked < 640px), each with `n` and a table toggle; caption under both: "Grades from papers uploaded in the {duringWindowDays} days from each student's first session with this tutor, compared with their latest grade in the {beforeLookbackDays} days before it. Grades worked out from estimated grade boundaries are left out. These grades come from Lemely's automatic marking, which is not as accurate as an examiner. Students choose their tutors, so this doesn't show what the tutor caused." Reviews (paged): stars, approved text, quarter, "A student", approved reply. Fees line. Actions: Book a session; Share my progress with this tutor; Report; Block.
**Insufficient state** (per figure, C-11 empty variant, neutral icon): "Results are hidden for now. We show them only when at least 5 students have a marked paper from their time with this tutor, and only when no one's grade could be worked out from them." (F8; covers k, SC-14 and the 90-day hold without saying which applied.)
**Interactions.** "Share my progress" opens a confirm sheet with the S-38 explainer, that it covers all subjects until the student stops it, that every visit is recorded and visible to them, and that their linked parents are told and can see who they share with. Confirm → S9.
**States.** No reviews: "No reviews yet." Not listed: "This tutor isn't taking bookings right now."
**Exits.** S-35, S-38, report sheet, G-13.

**S-35 · Book a session** — `/student/tutors/:tutorId/book`
**Contains.** C-24 first if not yet acknowledged. Subject, mode ("other" shows the tutor's note), duration, C-19 (14 days; "Show later dates" up to 28), optional first note, summary. **Counting notice** (row 8b): "If you have sessions with this tutor, your grades in this subject are counted, without your name, in their results. You can opt out in Tutors & your data." Fees line.
**Interactions.** Request → S-37. 409 `slot_taken`: "Someone just requested that time. Pick another." (picker refreshes). `student_busy`: "You already have a session then." `already_pending`: link to the request. `pending_limit`: "You have 5 requests waiting. Cancel one or wait for replies." 403 `email_unverified`: "Verify your email to book a session." with the verify link. 429: "You've made a lot of requests today. Try again tomorrow."
**Exits.** S-37, S-34.

**S-36 · My sessions** — `/student/sessions`
**Contains.** Tabs Upcoming / Past. Rows: tutor name, subject, time, mode, C-20.
**States.** Empty upcoming: "No sessions booked." → S-33. Empty past: "No past sessions yet."
**Exits.** S-37.

**S-37 · Session detail** — `/student/sessions/:bookingId`
**Contains.** C-20, tutor card, subject, time, mode, area; after accept the meeting link (`rel="noopener noreferrer"`) or place. Actions from `allowedActions`: Cancel ("You can cancel up to 24 hours before the start."), "Mark as completed" when `awaiting_outcome` ≥ 48 h ("Your tutor hasn't recorded this session. If it took place, you can mark it completed."), Review (from `reviewOpensAt`: "You can review this session from {date}."). C-21 with composer when `canPost` (C-24 first if needed). Review form: stars, optional text, "Your review text is checked by Lemely before others see it. Reviews show the season, not the date or your name." Counting notice with link to the opt-out.
**States.** Inside 24 h: "It's less than 24 hours to the start, so you can't cancel this session. Message your tutor." (row 18: only the tutor can cancel now). Cancelled late by the tutor (`cancelledLate`): "{Tutor} cancelled this session less than 24 hours before the start. Their reason: {cancelReason}" (plain text). Expired request: "The tutor didn't reply before the start time." Account too new to review: "You can review once your account is 14 days old."
**Exits.** S-36, S-34, report sheet.

**S-38 · Tutors & your data** — `/student/tutor-access`
**Contains.** 1) **Sharing:** each grant with tutor, since date, status; "Stop sharing" (confirm sheet: "They can't see your progress through Lemely's tutoring pages from now on." plus, when `alsoTeachesClasses` is non-empty, "This tutor also teaches your class {name}, so they still see your class progress there." and always "Your grades are still counted in their results unless you turn that off below."). Explainer (F29): "Your grades, predicted grades, target grades, papers' marks, weak topics, trend, at-risk warnings and the days you were active, for all subjects. Never your answer sheets, and never the time of day you used Lemely." "Your linked parents can see who you share with and each time a tutor looked." 2) **Who looked:** audit log (tutor, "viewed your progress" / "saw you in their student list", time), paged. 3) **Teachers who can see your progress through a class** (S16): class, teacher, school or "Independent class"; Leave for school-less classes (S17, confirm sheet: "You'll leave {class}. The teacher won't see your progress through this class any more."); "Ask your school" note for school classes. 4) **Results counting:** C-14 "Count my grades in my tutors' results" (default on) with: "Turning this off removes you from every tutor's results. When anyone's choice changes, that tutor's results are hidden for 90 days so no one can work out a grade from the change." 5) Blocked tutors with Unblock.
**States.** No grants: "You aren't sharing your progress with any tutor." Empty log: "No tutor has looked at your progress." No classes: section hidden.
**Exits.** S-34.

### Teacher (T) — tutoring is a separate section of the teacher portal

**T-15 · Tutoring home** — `/teacher/tutoring`
**Contains.** Listing status banner (draft / under review / listed / paused / rejected with note / suspended / closed). Requests awaiting reply (live pending only, F6; oldest first) with Accept/Decline. Upcoming sessions. "Awaiting outcome" sessions (Completed / No-show).
**States.** No profile: onboarding CTA → T-16. No requests: "No requests yet." Under review: "Lemely is reviewing your profile. You'll get a notification."
**Exits.** T-16, T-17, T-18, T-19, T-21.

**T-16 · Tutor profile & onboarding** — `/teacher/tutoring/profile`
**Contains.** C-15 steps: 1 Public card (first name, last initial, headline, subjects, modes, area from P3) with a live preview of the open-web card, a line: "Your first name, initial, city and subjects can identify you to people who know you." (PP-4), and the search notice (row 17, fixed copy, always shown above the C-14 toggle "Show my card in search engines", default on): "Your public card is on the open web, and search engines such as Google can list it. You can turn this off here at any time. After you turn it off, search engines can take a few weeks to drop your card."; 2 About (bio, qualification note, other-mode note); 3 Evidence (≤ 5, "Don't upload identity documents."; "Changing your documents removes the 'Documents seen' badge until Lemely looks again."); 4 Availability (→ T-17); 5 Submit (verified email required). After listing: edit form; editing name/initial/headline/bio/qualification/other-mode note shows "Saving sends your profile back for review and hides it until approved." Pause toggle. "Show my card in search engines" toggle with the same notice (saving it never sends the profile back for review).
**States.** Rejected: note shown, Resubmit. Suspended or closed: read-only with the admin note.
**Exits.** T-17, T-21, T-15.

**T-17 · Weekly availability** — `/teacher/tutoring/availability`
**Contains.** Seven day rows of time ranges (15-minute steps, zone label) with Add/Remove; "Cairo time; daylight saving is handled for you. Times in the hour when the clocks change can't be booked."
**States.** No rules: "Add at least one time so students can book."
**Exits.** T-15, T-16.

**T-18 · Session detail (tutor)** — `/teacher/tutoring/sessions/:bookingId`
**Contains.** Student label, requested by, subject, time, mode, area. Accept form (meeting link with the allowed services listed: Google Meet, Zoom, Microsoft Teams, Whereby; meeting place for in-person), Decline with reason, Cancel until the start (from `allowedActions`; when it is `cancel_with_reason` the sheet requires a reason: "You're cancelling less than 24 hours before the start. The student and any parents linked to their account will see your reason."; row 18), Completed / No-show after the end. C-21. "Shared progress: yes/no" from `studentShared` (link to T-20 if yes; no prompt to ask).
**Exits.** T-15, T-20.

**T-19 · My students** — `/teacher/tutoring/students`
**Contains.** Students with an active grant: label, sharing since, upcoming sessions. "Students choose to share their progress with you. They can stop at any time, and they can see each time you look."
**States.** Empty: "No students are sharing their progress with you yet."
**Exits.** T-20.

**T-20 · Student detail (tutor view)** — `/teacher/tutoring/students/:studentId`
**Contains.** The T-05 composition fed by the tutor projection (dates only, no times; no question ids; §e.2), with: "{Name} shared this with you on {date}. They can stop sharing at any time. Each visit is recorded and they can see it." **Removed relative to T-05:** attempt drill-down, remark, assign practice, at-risk acknowledge, integrity signals.
**States.** 403 `access_ended` → C-11: "{Name}'s progress is no longer shared with you." (one message for every reason, SC-11); react-query cache for this student cleared on 403.
**Exits.** T-19.

**T-21 · Profile preview & reviews** — `/teacher/tutoring/preview`
**Contains.** S-34 as students see it (T8; results omitted unless listed or under review), plus the review list from T21 with "Reply" (one reply; "Replies are checked by Lemely before students see them.") and the reply's moderation state.
**Exits.** T-16.

### Parent (P)

**P-05 · Child's tutoring** — `/parent/children/:childId/tutoring`
**Contains.** The child's tutors (derived from bookings) and sessions with C-20. Links: "Who {child} shares progress with" → P-08; "Find a tutor for {child}" → P-07.
**States.** None: "{Child} has no tutoring sessions."
**Exits.** P-06, P-07, P-08.

**P-06 · Session detail (parent, read-only)** — `/parent/children/:childId/sessions/:bookingId`
**Contains.** Same facts as S-37 including the meeting place after accept and the tutor's late-cancel reason; C-21 read-only ("Notes are between {child} and the tutor. You can read them and report anything that worries you."); Cancel and "Mark as completed" only if this parent made the request; Report (incl. "The session outcome is wrong").
**Exits.** P-05.

**P-07 · Find a tutor (parent)** — `/parent/tutors`, `/parent/tutors/:tutorId`, `/parent/tutors/:tutorId/book`
**Contains.** S-33 / S-34 / S-35 compositions in the parent shell, with a required "Booking for" child selector, the counting notice phrased for the child, and **no first-note field** (F19). "Share my progress", Block and C-24 are absent; Report stays.
**States.** No linked child: P-01's "link a child" explanation instead of the booking step.
**Exits.** P-06.

**P-08 · Who {child} shares progress with (read-only)** — `/parent/children/:childId/tutor-access` (row 16 i)
**Contains.** 1) The child's grants (PA6): tutor, since, status. No revoke control. Line: "{Child} decides who can see their progress. Only {child} can stop sharing. If something worries you, report it." 2) Who looked (PA7): tutor, "viewed {child}'s progress" / "saw {child} in their student list", time, paged. Report link per tutor.
**States.** No grants: "{Child} isn't sharing their progress with any tutor." Empty log: "No tutor has looked at {child}'s progress."
**Exits.** P-05.

### Platform admin (X) — utilitarian

**X-04 · Tutor approval queue** — `/platform/tutors`: table (name, subjects, submitted, state filter), "Email delivery: mock" banner when applicable. **Exits.** X-05.
**X-05 · Tutor application** — `/platform/tutors/:tutorId`: profile fields, account email, evidence (opens a 300 s download link; each open logged), approval history, open reports. Approve (required "I looked at the documents" checkbox → `documentsSeen`), Reject, Suspend / Reinstate, Close (confirm: "Closing cancels future sessions, ends every student's sharing and can't be undone.").
**X-06 · Moderation queue** — `/platform/moderation`: review texts and replies, oldest first.
**X-07 · Reports** — `/platform/reports`, `/platform/reports/:reportId`: safety concerns first; detail shows the snapshot and, for booking/note targets, the thread (view logged); resolve with dismiss / hide content / suspend tutor / cancel booking (before start only) / mark completed (disputed outcome) and a note.

### Accessibility and performance gate routes
Register in `web/scripts/audit.mjs` `ROUTE_REGISTRY` with `states[]`, and **add a `platform_admin` session to the audit registry** (it has none today, F22). axe 0 serious/critical and Lighthouse a11y ≥ 95 on: `/tutors`, `/tutors/:id`, `/student/tutors`, `/student/tutors/:id`, `/student/tutors/:id/book`, `/student/sessions`, `/student/sessions/:id`, `/student/tutor-access`, `/teacher/tutoring`, `/teacher/tutoring/profile`, `/teacher/tutoring/availability`, `/teacher/tutoring/sessions/:id`, `/teacher/tutoring/students`, `/teacher/tutoring/students/:id`, `/teacher/tutoring/preview`, `/parent/children/:id/tutoring`, `/parent/children/:id/sessions/:id`, `/parent/tutors`, `/parent/children/:id/tutor-access`, `/platform/tutors`, `/platform/tutors/:id`, `/platform/moderation`, `/platform/reports`. **Lighthouse runs on each route's default state only** (D3.17); the other states listed in each screen are covered by axe and the screenshot sheet, not Lighthouse (F22).
Lighthouse performance ≥ 80 on `/tutors`, `/tutors/:id` and every `/student/*` route above: **add these slugs to the performance list in `scripts/check_ui_gates.py`** (it covers only named slugs today, F22). Tutoring screens are lazy route chunks (`web/scripts/check-bundle-budget.mjs`).
320px no-horizontal-scroll on every route above.
**Evidence status:** CI runs no Playwright or audit job and `scripts/check.sh` skips both when the local stack is down, so e2e and audit results are local evidence, recorded as DELIVERY already records them (F22).

---

## e. Core modules and test strategy

### e.1 Pure core modules (`lemely/core/`; no DB, web, SQLAlchemy, FastAPI)

```python
# lemely/core/booking.py
BookingStateLit = Literal["requested", "accepted", "declined", "cancelled", "completed", "no_show", "expired"]
EffectiveState = Literal[BookingStateLit, "awaiting_outcome"]          # spelled out in code
Party = Literal["student", "parent", "tutor", "platform_admin", "system"]
Action = Literal["accept", "decline", "cancel", "complete", "no_show", "expire", "claim_complete"]
ACTIVE_STATES: Final[frozenset[str]] = frozenset({"requested", "accepted"})   # pinned to DDL + ORM where
CANCEL_CUTOFF: Final = timedelta(hours=24)        # row 9
MIN_NOTICE: Final = timedelta(hours=2)            # O-10
MAX_BOOKING_HORIZON: Final = timedelta(days=28)   # SC-8
ALLOWED_DURATIONS: Final = (45, 60, 90, 120)
MAX_PENDING_PER_STUDENT: Final = 5
NOTE_POST_GRACE: Final = timedelta(days=7)
OUTCOME_CLAIM_AFTER: Final = timedelta(hours=48)  # SC-17
SLOT_STEP: Final = timedelta(minutes=30)

@dataclass(frozen=True, slots=True)
class AvailabilityRule: iso_weekday: int; start_minute: int; end_minute: int
@dataclass(frozen=True, slots=True)
class BookingFacts:
    state: BookingStateLit; starts_at: datetime; ends_at: datetime
    viewer: Party; viewer_is_requester: bool; tutor_outcome_recorded: bool
@dataclass(frozen=True, slots=True)
class Refusal: code: str   # illegal_transition | cancel_window_closed | not_ended | already_started |
                           # not_requester | outcome_claim_not_open | beyond_horizon | not_bookable | ...

def normalize_rules(rules: Iterable[AvailabilityRule]) -> tuple[AvailabilityRule, ...]   # raises OverlappingRules
def occurrences(rules, *, zone: str, start: date, days: int) -> list[tuple[datetime, datetime]]
    # UTC bounds per occurrence via zoneinfo, each local endpoint round-trip checked (F27):
    # a nonexistent local time is clipped to the first valid instant; an ambiguous one uses fold=0
def bookable_slots(rules, *, zone, start: date, days: int, duration: timedelta,
                   busy: Sequence[tuple[datetime, datetime]], now: datetime) -> list[tuple[datetime, datetime]]
    # slots stepped in ABSOLUTE time inside each occurrence's UTC bounds; a slot whose local start or end
    # is ambiguous or nonexistent is not offered, so the clock-change hour is never bookable (F27)
def bookable(rules, *, zone, starts_at, ends_at, busy, now) -> Refusal | None   # == membership in bookable_slots
def effective_state(state, *, starts_at, ends_at, now) -> EffectiveState      # SQL mirror: §a.3 table
def check_transition(action: Action, facts: BookingFacts, *, now: datetime,
                     has_reason: bool = False) -> Refusal | None
    # row 18: action "cancel" on an accepted booking —
    #   viewer student/parent: now <= starts_at - CANCEL_CUTOFF, else Refusal("cancel_window_closed")
    #   viewer tutor: now < starts_at, else Refusal("already_started"); when now > starts_at - CANCEL_CUTOFF
    #   and not has_reason -> Refusal("reason_required")  (mapped to 422)
def is_late_cancel(*, cancelled_by: Party, cancelled_at: datetime, starts_at: datetime) -> bool
    # cancelled_by == "tutor" and cancelled_at > starts_at - CANCEL_CUTOFF; feeds BookingDTO.cancelledLate
def target_state(action: Action) -> BookingStateLit
def allowed_actions(facts, *, now, has_review: bool, blocked: bool, review_account_ok: bool) -> frozenset[str]
    # tutor viewer, accepted, starts_at - CANCEL_CUTOFF < now < starts_at -> "cancel_with_reason" (never "cancel")
def can_post_note(state, *, ends_at, now, blocked: bool, tutor_inactive: bool, frozen: bool) -> bool

# lemely/core/tutor_ratings.py
BAYES_PRIOR_MEAN: Final = Decimal("4.0"); BAYES_PRIOR_WEIGHT: Final = 5
NEW_THRESHOLD: Final = 3                         # row 6, counted in distinct students
REVIEW_EDIT_WINDOW: Final = timedelta(days=14)   # row 7
REVIEW_MIN_ACCOUNT_AGE: Final = timedelta(days=14)   # F7
def bayesian_score(rating_sum: int, rating_count: int) -> Decimal       # quantised numeric(7,6); (0,0) -> 4.000000
def aggregate_latest_per_student(reviews: Sequence[tuple[str, int, datetime]]) -> tuple[int, int]  # SC-16
def rating_display(rating_sum: int, rating_count: int) -> RatingDisplay
def review_open_at(ends_at: datetime) -> datetime                        # ends_at + NOTE_POST_GRACE
def review_edit_deadline(created_at: datetime) -> datetime
def quarter_label(created_at: datetime, zone: str) -> str                # "Jul–Sep 2026"

# lemely/core/tutor_grants.py
GrantStatus = Literal["active", "revoked", "expired", "blocked", "tutor_suspended", "tutor_closed",
                      "tutor_unavailable"]
@dataclass(frozen=True, slots=True)
class GrantFacts: created_at: datetime; revoked_at: datetime | None; revoke_reason: str | None
                  expires_at: datetime | None; tutor_listing_state: str; blocked: bool
def grant_status(facts, *, now) -> GrantStatus
    # precedence: revoke_reason (student->revoked, block->blocked, tutor_suspended, tutor_closed),
    # expired, blocked (active block), tutor_unavailable (listing_state not in {listed, pending_review}), active
def grant_is_valid(facts, *, now) -> bool    # SQL mirror used by T19/T20/S8/PA6, parity-tested

# lemely/core/tutor_outcomes.py — ADR-T04 definitions
OUTCOME_K_MIN: Final = 5                          # row 8
BEFORE_LOOKBACK: Final = timedelta(days=180)      # O-10
DURING_WINDOW: Final = timedelta(days=120)        # O-10; replaces "E + 60 d" (ADR-T04)
OPT_CHANGE_HOLD: Final = timedelta(days=90)       # SC-13d
MIN_MEMBER_ACCOUNT_AGE: Final = timedelta(days=30)   # SC-13e
@dataclass(frozen=True, slots=True)
class CohortMember:
    ref: int                       # opaque; never a user id
    first_session_start: datetime  # S: start of the first counted session in this subject
    eligible: bool                 # email verified by S (email_verified_at <= S, the FIRST verification), account >= 30 d at S, not opted out, never blocked this tutor
    ever_granted: bool             # any tutor_data_grants row for (student, tutor), live or revoked
    recent_change: bool            # opt-out changed, or a student->tutor block created, within OPT_CHANGE_HOLD
@dataclass(frozen=True, slots=True)
class AttemptFacts: origin: str; grade: str | None; boundary_source: str | None
                    subject_code: str | None; deleted: bool
def is_outcome_eligible(a: AttemptFacts, *, subject_code: str, ladder: Sequence[str]) -> bool
    # origin == "past_paper", grade on the ladder, boundary_source == "exact", same subject, not deleted.
    # SQL mirror in tutor_directory_repo, parity-tested (F9, F10)
@dataclass(frozen=True, slots=True)
class GradeObservation: ref: int; grade: str; recorded_at: datetime   # already eligible
def close_instant(m: CohortMember) -> datetime                      # S + DURING_WINDOW
def published_members(members, *, now, k) -> list[CohortMember]
    # closed (now >= close_instant) AND eligible, ordered by (close_instant, ref); first floor(n/k)*k (SC-13c)
def before_grade(m, obs, ladder) -> str | None    # latest in [S - BEFORE_LOOKBACK, S)
def during_grade(m, obs, ladder) -> str | None    # latest in [S, S + DURING_WINDOW)
def outcome_for_subject(members, obs, *, now, ladder=GRADE_ORDER, k=OUTCOME_K_MIN) -> SubjectOutcome
    # If any member (eligible or not) has recent_change: both figures insufficient.
    # Distribution over published members with a during grade: sufficient iff
    #   n_graded >= k  AND  never_granted(graded) in {0} ∪ [k, ∞)  AND  max bucket <= n_graded - 2   (SC-13a, SC-14)
    # Change over published members with both grades: same three tests on n_paired and higher/same/lower.
    # Insufficient -> counts None (n_without_grade too).

# lemely/core/contact_patterns.py (SC-7)
def find_contact_details(text: str) -> list[ContactMatch]
    # Egyptian mobiles (01[0125] + 8 digits; +20 / 0020 prefixes; Arabic-Indic digits ٠-٩; spaces, dots,
    # dashes as separators), emails, URLs and bare domains, @handles, wa.me / t.me / instagram / facebook /
    # snapchat / tiktok words. Tested for no false positives on grades, marks, times and paper codes.
MEETING_HOSTS: Final = ("meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com", "whereby.com")
def meeting_link_allowed(url: str) -> bool   # https, no userinfo, default port, host == or subdomain of MEETING_HOSTS

# lemely/core/tutor_directory.py
TimeOfDay = Literal["morning", "afternoon", "evening"]
TIME_OF_DAY_MINUTES: Final[Mapping[TimeOfDay, tuple[int, int]]]   # (360,720), (720,1020), (1020,1320)
def rule_matches(rule, days: frozenset[int], times: frozenset[TimeOfDay]) -> bool   # SQL mirror, parity-tested (F6)
def public_name(first_name: str, last_initial: str | None) -> str                  # "Sara M."
def validate_public_name(first_name: str, last_initial: str | None) -> None        # SC-25 allowlist
def student_label(display_name: str | None, user_id: uuid.UUID) -> str             # F12
def zone_label(zone: str) -> str                                                   # "Cairo time"

# lemely/core/keyset.py
def encode_cursor(endpoint: str, values: Sequence[object]) -> str
def decode_cursor(token: str, *, endpoint: str, types: Sequence[type]) -> tuple[object, ...]   # CursorError -> 422
```

Add an import-linter `forbidden` contract in `pyproject.toml`: sources `lemely.core.booking`, `.tutor_ratings`, `.tutor_grants`, `.tutor_outcomes`, `.contact_patterns`, `.tutor_directory`, `.keyset`; forbidden `lemely.db`, `lemely.web`, `lemely.io`, `lemely.app`, `sqlalchemy`, `fastapi`.

### e.2 The tutor projection of the student-detail DTO (minimal touch)

`lemely/web/student_detail_view.py` (new):

```python
def build_student_detail_for_tutor(*, student_id: uuid.UUID, display_name: str, history: StudentHistory,
                                   now: datetime, targets: Mapping[str, str] | None) -> StudentDetailDTO:
    """T-05 DTO for a granted tutor: the teacher builder's output, then the tutor projection (SC-20)."""
    dto = _student_detail_dto(RosterEntry(student_id=student_id, display_name=display_name),
                              history, now=now, acks={}, targets=targets)
    return project_for_tutor(dto)

def project_for_tutor(dto: StudentDetailDTO) -> StudentDetailDTO:
    """Truncate attempts[].recordedAt, trend[].recordedAt, engagement.lastActiveAt and at-risk evidence
    timestamps to the tutor-zone date; empty weaknesses[].questionIds."""
```

It imports `_student_detail_dto` from `lemely.web.routers.teacher` (`teacher.py:2322`) and `RosterEntry` from `lemely.db.class_repo` (`:88`). **Zero edits to `teacher.py`** (precedent for importing from it: `lemely/web/routers/classes.py:74`). `display_name` passed in is `student_label(...)`. The old parity test could not fail (F31); it is replaced by a **route-level** test: for one seeded student, T20's `detail` equals `project_for_tutor(<the teacher route's response with acknowledgements removed>)`, and T20's JSON has no key outside `TutorStudentDetailDTO`.

### e.3 Repositories and services
`lemely/db/models/tutoring.py` (all tutoring models + the `btree_gist` listener, §a.4), `lemely/db/tutor_profile_repo.py` (profiles, subjects, rules, evidence, approval, close), `lemely/db/tutor_directory_repo.py` (directory, facets, outcome statements), `lemely/db/booking_repo.py` (bookings, notes, §a.4b locks, constraint-name error mapping, effective-state predicates), `lemely/db/tutor_review_repo.py` (reviews, replies, `recompute_ratings(tutor_profile_id)` under `SELECT … FOR UPDATE` on the tutor row, used by every review change and by the CLI), `lemely/db/tutor_grant_repo.py` (grants, audit, preferences), `lemely/db/tutoring_safety_repo.py` (reports, blocks, admin access log), `lemely/db/email_outbox_repo.py` (`enqueue_in_session`, claim/mark for the sweeper job). Each multi-row change (transition + outbox; block + revoke + cancel + enrolment removal; review + aggregate) is one transaction; inbox writes follow commit (§b.4).

**Outcome statements (F9).** Two statements after the profile check, both with explicit predicates (the soft-delete loader criterion applies only to ORM entity selects, `lemely/db/session.py:178-218`, so it is never relied on):
1. *Cohort:* per (subject, student) from `tutor_bookings` where `accepted_at IS NOT NULL AND state IN ('accepted','completed','no_show') AND ends_at <= now()` for this tutor: `S = min(starts_at)`; joined to `users` (`email_verified_at`, `created_at`), `student_tutoring_preferences` (opt-out, `outcome_pref_changed_at`), `tutoring_blocks` (student → tutor's user, **any** row, `created_at`), `tutor_data_grants` (exists any row for the pair).
2. *Observations:* `attempts` for the cohort's students with `origin = 'past_paper' AND deleted_at IS NULL AND boundary_source = 'exact' AND grade = ANY(:ladder) AND subject_code = :subject` and `recorded_at` in `[S − 180 d, S + 120 d)`.
One DB test per exclusion (deleted, custom paper, quiz, other subject, estimated boundary, opted out, student-initiated block, unverified, account too new), each with a red case, listed as proof in the DELIVERY row.

**Query budget (no N+1; asserted with a `before_cursor_execute` counter, precedent `tests/test_self_review_repo.py:2413`), F24:**
| Endpoint | Statements, independent of row count |
|---|---|
| P1/SP1 directory, first page | 3 (profiles incl. block anti-join for SP1; subjects of page; facets) |
| P1/SP1 later pages | 2 |
| P2 / SP2 | 2 (profile + listed/blocked predicate; subjects) |
| SP4 outcomes, T8 outcomes part | 3 (profile listed/blocked check + subject names; cohort; observations) |
| S1/T9/PA1 booking lists | 2 (bookings joined to profiles/users; subjects of page tutors) |
| T19 student list | 3 (grant validity + rows; audit insert batch; upcoming counts) |
| T20 student detail | 1 transaction (validity + audit), then the existing `history_store.load` + `target_grades_for` |
| S11, PA7 audit log | 1 (PA7: + the link check) |

### e.4 Test strategy

Pyramid: many pure unit tests, DB integration for every constraint and transaction, the generated authz sweep plus object-level tests, and a few Playwright journeys. Gemini is not on any tutoring path; no test makes a network call (email via the mock). **Every test listed in `docs/tutoring/THREAT-MODEL.md` §7 is required**, each with a case that fails without its fix, with these adjustments: the verified-email test excludes R1 (`test_authz_verified_email_required_for_booking_review_grant_submit`; plus `test_authz_report_allowed_without_verified_email`); the cohort tests use the ADR-T04 membership rule; the review-visibility tests become `test_review_create_refused_before_notes_window_closes`; the `_headers` noindex test (`test_headers_file_has_tutors_noindex_rule`) is replaced by the row 17 worker tests below and `test_headers_file_has_no_tutors_rule`.

**Unit (pure; `tests/test_core_booking.py`, `test_core_tutor_ratings.py`, `test_core_tutor_grants.py`, `test_core_tutor_outcomes.py`, `test_core_tutor_directory.py`, `test_core_contact_patterns.py`, `test_core_keyset.py`)**
- Booking: exhaustive table over (state × action × viewer × requester flag × outcome-recorded × time position {> 24 h before, < 24 h before, in progress, < 48 h after end, ≥ 48 h after end}); `effective_state` per state and time; `can_post_note` table (§a.3); `ACTIVE_STATES` equals the predicate parsed from the migration and from the ORM `where`. Late cancel (row 18): `test_tutor_cancel_inside_24h_requires_reason`, `test_tutor_cancel_inside_24h_with_reason_allowed`, `test_tutor_cancel_after_start_refused_already_started`, `test_student_cancel_inside_24h_refused_cancel_window_closed`, `test_parent_cancel_inside_24h_refused_cancel_window_closed`, `test_cancel_at_exactly_24h_is_not_late`, `test_allowed_actions_tutor_inside_24h_offers_cancel_with_reason_only`, `test_is_late_cancel_truth_table`, `test_cancel_cutoff_pinned_to_late_cancel_check_text` (the `24 hours` literal in the migration and ORM CHECK equals `CANCEL_CUTOFF`).
- Slots (F27): Cairo DST end 2026-10-29 (Thursday 17:00 rule → 14:00Z; 2026-11-05 → 15:00Z; read from installed tzdata); a Thursday 22:00–24:00 rule on 2026-10-29 offers no slot starting or ending in the repeated hour and never renders two identical labels; DST start 2026-04-24 00:30 (nonexistent; `zoneinfo` does not raise, so the round-trip check is what catches it) offers nothing in the gap; `bookable_slots` never overlaps busy, never leaves a rule, respects `MIN_NOTICE`, horizon, step and durations; `bookable` == membership in `bookable_slots`.
- Ratings: n=1 five-star ranks below 20 reviews averaging 4.5; `bayesian_score(0, 0) == 4.000000`; `aggregate_latest_per_student` counts a student's latest review once; "new" for 0–2 students; rounding; quarter labels.
- Grants: full truth table of `grant_status` including precedence and every listing state.
- Outcomes (ADR-T04): k boundary per figure on `n_graded`/`n_paired`, not cohort size (cohort 5, n_graded 4 → insufficient, F8); never-granted count 1..4 → insufficient, 0 or ≥ 5 → sufficient; largest bucket n−1 → insufficient, n−2 → sufficient; window edges (`S−1s`, `S`, `S+120d−1s`, `S+120d`); published set moves only in steps of k; recent change → insufficient for both figures; ineligible members excluded; ladder argument honoured (a 9–1 ladder works unchanged); `is_outcome_eligible` truth table.
- Contact patterns: Egyptian mobiles in Latin and Arabic-Indic digits with separators; emails; URLs and bare domains; handles; no false positive on "A*", "72/80", "17:00", "0625/42"; `meeting_link_allowed` rejects `http:`, userinfo, non-default ports, `wa.me`, look-alike hosts (`zoom.us.evil.com`).
- Directory: `rule_matches` table; `validate_public_name` rejects digits, URLs, `@`, bidi controls, accepts Arabic names; `student_label` never contains `@`; typed cursor round-trip, wrong endpoint, wrong types, malformed → error.

**DB integration (Postgres; each test module defines its own `pg_engine`/`pg_sessionmaker` the way `tests/test_db_schema.py:319` does — they are not shared fixtures, F23)**
- Migration tests named by content, not number (F35): `tests/test_migration_tutoring_enums.py`, `…_tutor_profiles.py`, `…_outbox_parent_links.py`, `…_tutor_bookings.py`, `…_tutor_reviews.py`, `…_tutor_grants.py`, `…_tutoring_safety.py`: upgrade → downgrade → upgrade on `migrated_sessionmaker_with_downgrade`; constraints by name in `pg_constraint`/`pg_indexes`; `pg_get_constraintdef` contents (F20); the enum/preference-column pin passes; downgrade of the enums revision leaves `btree_gist` installed.
- `test_create_all_on_fresh_database_installs_btree_gist` (F2, §a.4).
- Late cancel (row 18, DB and route): `test_ck_late_tutor_cancel_requires_reason` (red case: a tutor-cancelled row inside 24 h with a NULL reason is rejected; the same row with the `IS NOT NULL` conjunct removed from the CHECK is accepted), `test_t13_late_cancel_without_reason_422`, `test_t13_late_cancel_with_reason_200_reason_visible_to_student_and_parent`, `test_s3_late_cancel_409_cancel_window_closed`, `test_pa4_late_cancel_409_cancel_window_closed`, `test_late_cancel_notice_and_email_carry_no_reason_text`, `test_late_cancel_leaves_outcomes_unchanged` (byte-identical `OutcomesDTO`).
- Constraint tests: both exclusion constraints, one-pending index, availability non-overlap, one live grant, every CHECK, composite FKs (a review whose `tutor_profile_id` differs from its booking's is rejected), RESTRICT (`test_delete_user_with_booking_restricted`, `test_delete_tutor_user_restricted`, F18/SC-21), outbox `ON CONFLICT DO NOTHING` does not abort the caller's transaction.
- Predicate parity (F6): each §a.3 effective-state predicate, the live pending count, `rule_matches`, `grant_is_valid` and `is_outcome_eligible`, evaluated in SQL over a generated table of inputs, equal their core functions.
- **Concurrency (`tests/test_concurrency.py`, own sessions, barrier start):** the slot race (8 threads → exactly 1 `201`); accept vs cancel; concurrent reviews by one student → aggregate counts them once; concurrent grants; plus every race in THREAT-MODEL §7 (block vs create, suspend vs create, suspend vs accept, block vs note, unlink vs parent create, revoke vs T20, grant vs block, pending limit at most 5, two redeems at the parent cap).
- Notifications and email: `test_transition_commits_when_inbox_write_raises` (the transition returns 200, the outbox row exists, the error is logged: replaces the old "transactionality" test, F3); `test_failed_transition_writes_no_outbox_row`; `test_two_notes_one_booking_two_notices` and `test_revoke_then_regrant_notifies_parents_twice` (F17); `test_parent_note_notice_once_per_day_tutor_notes_only`; `test_mock_provider_marks_skipped_not_sent`; `test_unverified_and_placeholder_recipients_skipped`; `test_daily_cap_skips_beyond_cap`; `test_deliver_job_claims_with_skip_locked_across_two_workers`; `test_failed_row_never_retried`; `test_outbox_context_schema_rejects_extra_keys`; `test_last_error_has_no_address`; email `context` never contains note text, link, location or an address.
- Outcomes: `test_outcomes_marking_complete_no_show_or_tutor_block_changes_nothing` (byte-identical `OutcomesDTO` from T8 and SP4 before and after each action, F1); one test per exclusion (§e.3); the hold after opt-out, opt-in and a student block.
- Audit: each 200 on T20 writes exactly one `detail` row; T19 one `list` row per listed student; 403/404 write none; audit insert raising → 500 with no student data; A2/A10 write `tutoring_admin_access` rows and fail closed.
- Query-count tests per the budget table.

**Authz**
- `tests/test_authz_matrix_complete.py` with §c.1 rows: 67 new 401 cases, 257 new 403 cases, guard freeze, real-token cases for the three new guard sets.
- `tests/test_web_tutoring_authz.py`: one test per rule O1–O29 with a red case; the route-level T20 projection test (§e.2).
- `tests/test_parent_link_integrity.py`, `tests/test_class_side_door.py`: §c.4 list.

**Config and deploy:** `tests/test_deploy_headers.py` parses `web/nginx.conf` (`test_nginx_index_html_sets_x_robots_tag_for_tutors`; security headers repeated inside `location = /index.html`), `robots.txt` (`test_robots_txt_does_not_disallow_tutors`) and `web/public/_headers` (`test_headers_file_has_no_tutors_rule`); `test_tutoring_private_routes_send_no_store`; `test_public_routes_only_p1_p3_cacheable`; `persistAllowlist.test.ts` "excludes tutoring query keys"; staging `curl -sI` steps in the deploy checklist (§b.5).
**Indexing (row 17):** `tests/test_web_tutor.py::test_indexable_defaults_true_and_tutor_can_opt_out`, `::test_indexable_change_does_not_send_profile_back_to_review`; `tests/test_web_tutoring_public.py::test_p2_carries_indexable_and_p1_does_not`, `::test_p2_404_identical_for_unlisted_paused_suspended_closed_unknown`. `web/tests/unit/workerTutorRobots.test.ts`: "serves the SPA shell for /tutors with noindex, follow"; "omits X-Robots-Tag for a card whose lookup says indexable"; "sends noindex, nofollow when the tutor opted out"; "sends noindex, nofollow when the lookup 404s"; "fails closed on lookup error, timeout, non-JSON and a missing or non-boolean field"; "fails closed for a non-UUID id or a deeper path without calling the backend"; "the lookup carries no cookie or authorization and targets only /api/public/tutors/{id}"; "sets the five security headers on /tutors responses"; "wrangler run_worker_first lists /api/*, /tutors and /tutors/*"; "/api/* proxying is unchanged". Red case recorded in the task: forcing the indexable branch to always omit the header turns the opted-out and 404 tests red.

**E2E (Playwright, `web/e2e/tutoring-*.spec.ts`, seeded via `scripts/seed_e2e.py` extensions, F23)**
1. Student discovers and books: `/tutors` → sign in → `/student/tutors` with subject + availability filters → profile (sufficient results seeded for one tutor, insufficient for another) → C-24 → book → tutor accepts in a second context → student sees the meeting link.
2. Tutor onboards: teacher signs up and verifies → T-16 steps → submit → admin approves on X-05 → tutor appears on `/tutors` → student grants on S-34 → tutor opens T-20 → S-38 and the parent's P-08 show the visit.
3. Consent revoked → denied: student stops sharing on S-38 → tutor reloads T-20 → "no longer shared" state, no data, no new audit row.
4. Parent books for child: parent `/parent/tutors` → book (no first-note field) → child sees the session in S-36 → parent's P-06 has no composer.
5. Double booking: two students race for one slot → one sees "Someone just requested that time."

**A11y / Lighthouse / visual:** routes and states in §d registered in `ROUTE_REGISTRY`; screenshots via `web/scripts/capture_surface.mjs`.

---

## f. Migration plan

**Before wave 1 (F36; amended by PLAN rev 2, P5):** merge `origin/develop` into `feat/tutoring-marketplace` with one signed merge commit (117 commits ahead of `314ef8ec` at review time; it changes `lemely/web/routers/teacher.py` and `lemely/web/app.py`). The branch is already published on origin, so it is never rebased (a rebase would need a force-push). `git merge-tree --write-tree HEAD origin/develop` reported no conflict on 2026-10-25 at `e80cb9fc`. Then re-run `alembic heads` (`0043_merge_heads` at review time, single head) and re-check every line citation in this SPEC. If the head moved, re-point `0044.down_revision` and renumber; migration **tests are named by content**, so renumbering touches no test name (F35).

| Revision (≤ 32 chars) | Wave | Contents (all additive) | Downgrade |
|---|---|---|---|
| `0044_tutoring_enums_ext` | 1 | `CREATE EXTENSION IF NOT EXISTS btree_gist`; the 16 new enum types; 8 `ADD VALUE`s on `notificationtype`; 8 boolean columns on `notification_preferences` | delete `notifications` rows of the 8 new types (pre-0044 code cannot load them, precedent 0039); drop the 8 columns; drop the 16 types. **Never drops `btree_gist`** (it may predate 0044, F35). The 8 `notificationtype` values stay (no `DROP VALUE`; precedent 0039) |
| `0045_tutor_profiles` | 1 | `tutor_profiles`, `tutor_subjects`, `tutor_availability_rules` (+ exclusion), `tutor_evidence_files`, `tutor_approval_events`, `tutoring_admin_access` | drop in reverse; storage objects are not deleted by a downgrade (documented) |
| `0046_tutoring_outbox_links` | 2 | `email_outbox`, `parent_link_events` | drop in reverse |
| `0047_tutor_bookings` | 2 | `student_tutoring_preferences`, `tutor_bookings`, `tutor_booking_notes` | drop in reverse |
| `0048_tutor_reviews` | 3 | `tutor_reviews`, `tutor_review_replies` | drop; then `UPDATE tutor_profiles SET rating_count = 0, rating_sum = 0, rank_score = 4.000000` (the zero-review score, written as a literal, F35) |
| `0049_tutor_grants_audit` | 4 | `tutor_data_grants`, `tutor_access_audit` | drop in reverse. **Destroys the audit log**; incident response snapshots it first (documented) |
| `0050_tutoring_safety` | 5 | `tutoring_reports`, `tutoring_blocks` | drop in reverse |

Numbers now follow wave order. `lemely tutoring recompute-ratings [--tutor <id>]` (CLI, `lemely/app/cli.py`) calls `TutorReviewRepository.recompute_ratings`, the same function every review change uses (F35, O-12).

**`ADD VALUE` inside the migration transaction (0044).** Alembic runs one `alembic upgrade` in a single transaction, and 0044's eight `ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS` run inside it. PostgreSQL 12+ allows that only while no later statement in the same transaction uses a new label, and nothing in 0044–0050 does. A later revision that writes or compares one of these labels (a backfill, or a partial index or CHECK naming `'booking_request'`), and can run in the same upgrade as 0044, must run that statement inside `with op.get_context().autocommit_block():`, which commits the open transaction, and with it the new labels, first. Otherwise the upgrade fails with `unsafe use of new value`.

**Release groupings** (amended by PLAN rev 2, P8): the five groupings below say which migration, core, repo, routes, authz rows, tests and screens belong together. The feature ships as **one pull request** (base `develop`, opened by the lead as a draft at the first integration so CI runs on every integration push; never merged by an agent; PLAN §0.10). The `web/src/portals/marketing/dataHandling.ts` sentences, each with its source comment as that file requires (F16), land once, in PLAN W8, because nothing ships before that PR merges.
1. Profiles, admin approval and close, public and logged-in directory, areas route (G-16, G-17, S-33, S-34 without results, T-15, T-16, T-17, T-21, X-04, X-05). `dataHandling.ts`: the public tutor card fields. Hot files: `lemely/db/models/__init__.py` (one import), `lemely/io/storage.py` + `storage_local.py` (`create_signed_url(..., disposition=None)`, additive, SC-22), `lemely/web/app.py`, `tests/test_authz_matrix_complete.py`, `web/nginx.conf`, `web/worker/index.ts` + new `web/worker/robots.ts`, `web/wrangler.jsonc` (row 17; `web/public/_headers` is read by a test, not edited).
2. Booking, notes, outbox and the sweeper job, safety notice, **row 14 (§c.4)** (S-35..S-37, T-18, P-05..P-07). `dataHandling.ts`: bookings, notes readable by linked parents and by admins on report, parent-link notices. Hot files: §c.4's list, `lemely/web/scheduled_notifications.py` (one job appended in `Sweeper.sweep_once`), `lemely/web/deps.py` (`get_sweeper` wiring, provider), `lemely/runtime/config.py` (`[tutoring] email_daily_cap`), `lemely/web/schemas_me.py`, the three notification-type mirrors in `web/src/lib`.
3. Reviews and moderation (S-34 reviews, S-37 review, T-21 replies, X-06).
4. Grants, audit, tutor student view, outcomes, opt-out, parent grant view, class-access section (S-38, T-19, T-20, P-08, S-34 results). `dataHandling.ts`: grants, the audit log and parents' view of it, default-on counting with opt-out and the 90-day hold, class teachers' visibility.
5. Reports and blocks (report/block sheets, X-07).

**Reversibility (F5).** Every revision is additive and nothing is backfilled, but **a Cloud Run revision rollback past wave 1 is not automatically safe**: pre-0044 code raises `LookupError` (a 500) opening the inbox of anyone holding a notification of a new type, exactly as `docs/deployment.md` §5.7 records for 0039's `review_withdrawn`. Wave 1 adds to `docs/deployment.md` §5.7 a tutoring entry: before any revision rollback across a tutoring release, run

```sql
DELETE FROM notifications WHERE type IN ('booking_request','booking_update','booking_note','tutor_access',
  'tutor_review','tutor_listing','parent_link','tutoring_report');
```

and expect tutoring data (profiles, bookings, grants) to be invisible, not lost, until the roll-forward. A schema downgrade past 0044 also drops the eight `notification_preferences` toggles; they come back as `true` on the roll-forward, so a user who had turned one off receives those notices again. The forward fix stays the preferred path. A wave-0 change that makes the inbox reader skip unknown types would remove the need for the `DELETE`; it is not adopted because it changes existing notification code for a rollback convenience (noted, not required).

---

## g. DELIVERY.md changes

Add a block to §3 Feature inventory:

| Feature | Phase | Status | Key implementation files | Proving tests |
|---|---|---|---|---|
| **Tutoring marketplace** | | | | |
| Tutor profiles + platform-admin approval ("documents seen" means a Lemely admin saw uploaded documents; no identity or background check — §5.7) | tutoring | Delivered (limited) | `lemely/db/tutor_profile_repo.py`, `lemely/web/routers/{tutor,admin_tutoring}.py` | `tests/test_web_tutor.py`, `tests/test_web_admin_tutoring.py` |
| Public tutor directory, minimal card; cards indexable by search engines by default with a per-tutor opt-out, directory page never indexed (§5.7) | tutoring | Delivered (limited) | `lemely/web/routers/tutoring_public.py`, `web/src/portals/marketing/`, `web/worker/robots.ts`, `web/wrangler.jsonc` | `tests/test_web_tutoring_public.py`, `tests/test_deploy_headers.py`, `web/tests/unit/workerTutorRobots.test.ts`, `web/e2e/tutoring-discover.spec.ts` |
| Logged-in directory: subject / mode / area / rating / availability filters, Bayesian ranking, keyset paging | tutoring | Delivered | `lemely/core/{tutor_ratings,tutor_directory}.py`, `lemely/db/tutor_directory_repo.py` | `tests/test_core_tutor_ratings.py`, `tests/test_tutor_directory_repo.py` |
| Booking: request / accept / decline / cancel (student and parent up to 24 h before; the tutor until the start, with a reason inside 24 h) / complete / no-show, DB-enforced no double booking (pending requests are shown as expired when read, not changed by a timer — §5.7) | tutoring | Delivered (limited) | `lemely/core/booking.py`, `lemely/db/booking_repo.py` | `tests/test_core_booking.py`, `tests/test_booking_repo.py`, `tests/test_concurrency.py` |
| Booking-event email (outbox, delivered by the existing sweeper, first attempt only — §5.7) | tutoring | Delivered (limited) | `lemely/db/email_outbox_repo.py`, `lemely/web/tutoring_email.py`, `lemely/io/notify_email.py` | `tests/test_email_outbox_repo.py`, `tests/test_tutoring_email.py` |
| Booking notes thread, contact-detail check, report + admin moderation (reactive only — §5.7) | tutoring | Delivered (limited) | `lemely/core/contact_patterns.py`, `lemely/db/{booking_repo,tutoring_safety_repo}.py` | `tests/test_core_contact_patterns.py`, `tests/test_web_tutoring_safety.py` |
| Reviews (one per completed session, text moderated, one tutor reply, 14-day edit, one rating per student) | tutoring | Delivered | `lemely/db/tutor_review_repo.py` | `tests/test_tutor_review_repo.py` |
| Student data grants + audit log visible to the student and, read-only, to linked parents | tutoring | Delivered | `lemely/core/tutor_grants.py`, `lemely/db/tutor_grant_repo.py`, `lemely/web/routers/parent_tutoring.py` | `tests/test_core_tutor_grants.py`, `tests/test_web_tutoring_authz.py` |
| Tutor's view of a granted student (derived analytics only, dates without times) | tutoring | Delivered | `lemely/web/student_detail_view.py`, `lemely/web/routers/tutor.py` | `tests/test_web_tutoring_authz.py` (route-level projection test) |
| Parent books for a linked child; read-only views of the child's sessions | tutoring | Delivered | `lemely/web/routers/{tutoring_directory,parent_tutoring}.py` | `tests/test_web_parent_tutoring.py`, `web/e2e/tutoring-parent.spec.ts` |
| Parent-link and class-join notices (existing routes, row 14) | tutoring | Delivered | `lemely/db/{parent_repo,invite_repo,class_repo}.py` | `tests/test_parent_link_integrity.py`, `tests/test_class_side_door.py` |
| Past-student outcome figures (k ≥ 5 on graded students, suppression rules, default-on counting with opt-out; rests on automatic marking — §5.1, §5.7) | tutoring | Delivered (limited) | `lemely/core/tutor_outcomes.py`, `lemely/db/tutor_directory_repo.py` | `tests/test_core_tutor_outcomes.py`, `tests/test_tutor_outcomes_repo.py` |

§4 Deferred: extend the Payments row: "The tutoring marketplace shows no prices; fees are agreed outside Lemely."

New §5.7 text:

> ### 5.7 Tutoring marketplace
> - **Nothing happens on a timer except email delivery.** Lemely has a sweeper that runs every 60 seconds inside the API process (§5.3). This feature adds one job to it: sending queued booking and safeguarding emails, once each. A failed email stays `failed` and is never retried. An email can wait in the queue while no server instance is running (Cloud Run scales to zero), and a crash at the wrong moment can send one twice. Pending requests whose start time passes are shown as expired; nothing changes them in the database until that student next requests that tutor. There are no reminders and no automatic completion.
> - **Email may be off without anyone noticing a failure.** Without an `[email] api_key`, emails are recorded as skipped (reason `mock_provider`), startup logs a warning, and the admin console says "Email delivery: mock". Emails go only to verified addresses, and at most 60 a day are sent, because the free provider tier allows 100 and is shared with sign-up mail.
> - **"Documents seen" means a Lemely admin looked at documents the tutor uploaded.** It is not an identity check, a qualification check with the issuer, or a criminal-records check. Changing the documents removes the badge until an admin looks again.
> - **Moderation is reactive.** Nothing reads notes, reviews or replies automatically. Review text and replies are read by an admin before they are public; notes are read only when someone reports them. Free text is checked for phone numbers, emails, links and social handles, and meeting links must come from Google Meet, Zoom, Microsoft Teams or Whereby. A determined person can still spell a number out in words.
> - **Child-safety choices made against the architect's recommendation** (ADR-T02): a student of any age can share all their progress with a tutor, indefinitely, without a parent's approval; parents are told and can see who the child shares with and each time a tutor looked, but cannot stop it; notes between a tutor and a minor are free text. **A student can remove a parent link at any time. The parent is told once, when it happens, and nothing after that.** A student chooses who their linked parents are (up to 4). Every student sees a safety notice before their first booking.
> - **Completion is recorded by the tutor**, or by the student or the parent who booked if the tutor has recorded nothing 48 hours after the session. Ratings count each student once.
> - **Outcome figures are not evidence of what a tutor caused.** They rest on Lemely's automatic marking (§5.1), leave out grades from estimated boundaries, and students choose their tutors. Students are counted unless they opt out. A figure appears only when at least 5 students have a marked paper, only when no single student's grade could be worked out from it on its own, and is hidden for 90 days after anyone's counting choice changes.
> - **Accepted risk: a tutor can sometimes work out one student's grade by comparing the figure over time** (decision row 13, ADR-T04 R5). Students enter a tutor's figure 120 days after their first session, five at a time, and the tutor can work out when. If at least five students who never shared are already in the figure, and four of the five students who enter next share their progress with the tutor, the tutor can compare the figure before and after and learn the fifth student's grade and whether it went up, even though that student never shared anything. No action by the tutor causes the change; they only have to look on the right day. The user chose live figures over a monthly snapshot knowing this.
> - **"Logged in" is not a strong boundary.** Any free student account with a verified email can see full profiles, reviews and outcome figures. Reviews show "A student" and a season, but a tutor with few students can often guess who wrote one, and the rating count changes when a review is added.
> - **Search engines can list tutors (decision row 17, chosen over the recommended "never index").** A listed tutor's public card (first name and initial, headline, subjects, modes, city) can appear in search results unless the tutor turns that off in their profile; onboarding says so. The directory page itself is never indexed. An opt-out reaches Lemely's edge within a minute, but a search engine drops a card only when it next visits it, which can take weeks. Lemely's edge asks the API about each card; if that check fails for any reason, the card is marked not to be indexed. The self-hosted (nginx) deployment never lets search engines index tutor pages. There is no sitemap.
> - **Late cancellation.** A student or parent cannot cancel inside 24 hours of the start. The tutor can, with a reason the student and linked parents see in the session; notifications and emails never carry the reason.
> - **No per-IP rate limit in the application** on the public directory. Responses are cached at the edge for 60 seconds, which spares the database but does not slow a scraper; a Cloudflare rate-limit rule is an ops step.

---

## h. Open items and things not verified

**Decision points for the user:** none open. Rev 3 resolved every one (§i.1). Nothing below blocks a wave.

**Not verified (each has a named check and a safe default):**
- **O-13** `alembic heads` after the wave-0 merge of `origin/develop` (§f). `git diff --name-only 314ef8ec origin/develop -- lemely/db/migrations/versions` was empty on 2026-10-25 (`origin/develop` @ `e80cb9fc`), so `0043_merge_heads` is expected to stay the single head; the plan's wave 0 re-runs `alembic heads` after the rebase.
- **O-14** `btree_gist` on CI's Debian `postgres:16`: not run locally; the first CI run of `test_create_all_on_fresh_database_installs_btree_gist` proves or disproves it. The Supabase advisor will flag `extension_in_public`; installing into `extensions` is not portable to CI, so the warning is accepted.
- Whether `env.ASSETS.fetch()` returns the SPA shell (200, `text/html`) for `/tutors/<id>` under `not_found_handling: "single-page-application"`. Cloudflare's "SPA shell" example implies it does; checked on staging by the §b.5 deploy checklist before release.
- Whether `_headers` rules are applied to `env.ASSETS.fetch()` responses. The docs say they are not applied to responses generated by Worker code; the worker sets every header itself and `_headers` has no `/tutors` rule, so either answer is safe.
- Whether search engines discover cards through a `noindex, follow` directory page with no sitemap (third-party crawler behaviour; not verifiable here).
- Whether the Cloudflare plan in use offers a WAF rate-limiting rule.
- Whether a Cloudflare cache rule already exists for `/api/*` (the worker code sets none).
- `pip-audit` was not run (not installed). `react-router`/`react-router-dom` should be upgraded past GHSA-qwww-vcr4-c8h2 (SPA mode, probably not exploitable).

---

## i. Decided items, constants and accepted limits

### i.1 Resolved at rev 3 (2026-10-25)
- **D-1 → row 17.** The public card is indexable by default; the tutor opts out on T-16; the edge worker honours it by a lookup on P2 (§b.5); onboarding states it plainly. Chosen over the recommended "always noindex".
- **D-2 → row 18.** Inside 24 hours of the start only the tutor may cancel, with a reason shown to the student and linked parents (§a.3, §b.2 T13, §c.3 O30). Outcome figures are unaffected: a cancelled booking never enters the cohort.
- **O-4, O-5, O-6, O-7, O-11 → row 19, confirmed as read:** the recorded ladder A*–E, U; availability as Cairo wall clock plus zone with UTC instants; a parent cancels or completes only bookings they requested, is read-only otherwise, and may report; UI spec §1.4 principles 3 and 5 are reworded and MISSION §3 "their teachers" includes a tutor the student granted (both in the Phase 4 docs, ADR-T02).
- **O-15 → decided: no subscription gate.** No tutoring route checks a subscription or an activation (X-02): a tutor needs no activated subscription to create, submit or run a profile, and students and parents need none to browse, book or grant. Verified that `lemely/web/deps.py` has no subscription dependency today, so this adds nothing and removes nothing.
- **D-3 (information, F4) → locked row 12 stands.** A 60-second sweeper exists (`lemely/web/scheduled_notifications.py`) and is used only for first-attempt email delivery. Email retry and persisted request expiry are not built; adding either is a new user decision against row 12.
- **Optional safeguards (THREAT-MODEL §6 [U]) → not adopted** at spec review or rev 3, so not built: an in-person request needing a linked parent with a verified email (CS-5); a system report when a grant or in-person booking follows a parent unlink within 14 days (CB-1); a logged, time-boxed admin read of every thread of a reported tutor (CS-8).

### i.2 Constants

**Proposed constants (architect's defaults, tunable, not user decisions) — O-10:** `MIN_NOTICE` 2 h; durations 45/60/90/120; `MAX_PENDING_PER_STUDENT` 5; `MAX_BOOKING_HORIZON` 28 days; Bayesian prior 4.0 with weight 5; outcome windows 180 days before / **120 days from the first session**; opt-change hold 90 days; member account age 30 days; review account age 14 days; outcome claim after 48 h; notes open until 7 days after the session; evidence 5 files × 10 MiB, links valid 300 s; quotas 10/10/20 per day; email cap 60 per day; time-of-day buckets 06–12/12–17/17–22.

### i.3 Known limits accepted in this spec
- **No sitemap** for tutor cards (row 17 makes cards indexable; discovery relies on links).
- **Self-host deploy:** nginx never lets search engines index tutor pages (no per-tutor lookup there).
- **O-9** No per-IP limit inside the app (the existing limiter is process-local); edge cache + an optional WAF rule (§b.5).
- **O-12** Accounts that own a tutor profile or are the subject of a booking cannot be deleted (RESTRICT) until an offboarding procedure exists; ratings are recomputed from reviews by one function, so no review deletion can leave them stale.
- **O-16** No limit on how long after a session a review can be written.
- **O-17** Platform-admin reads of notes and evidence are logged in `tutoring_admin_access` (SC-23) but not shown in the student's access log, which records tutors.
- **O-18** Blocks are student ↔ tutor only; parents cannot block.
- **O-19** Booking emails to legacy placeholder parent addresses are skipped; SMS stays the mock (`deps.py:296`), so phone-only parents get in-app notices only.
- A rejected reply cannot be replaced (one reply per review, RF-7).
- Re-joining a tutor's school-less class after a block or suspension is not refused (row 14 adds no permission change to the join routes); the student's linked parents are told when it happens.

### i.4 Clarifications settled during Wave 1 (2026-10-26)

Written by the lead from the T02/T03/T04 task reviews. Each is the reading the code already implements, or a rule a later task must follow.

**Ratings and directory (T02).**
- `aggregate_latest_per_student` returns `(rating_sum, rating_count)`, sum first, so `bayesian_score(*aggregate_latest_per_student(rows))` works. On an exact `created_at` tie the later entry wins; the SQL equivalent (`DISTINCT ON (student_id)`) must break ties by `id` descending.
- `rule_matches`: an empty day set or time set means no filter on that dimension. Rule and filter overlap on half-open minute ranges. The SQL mirror (T06) must do the same.
- `student_label`: the display name is used only when, after stripping format characters (Cf) and NFKC normalisation, it contains no `@` and `find_contact_details` finds nothing; otherwise the label is `"Student " + sha256(str(user_id).encode("ascii")).hexdigest()[:4].upper()` (hyphenated, lowercase UUID text).
- `review_edit_deadline` = `created_at + 336 elapsed hours`, in UTC. A SQL guard must use `interval '336 hours'` or a UTC session, never `interval '14 days'` in a Cairo session (wall-clock across a DST change).
- **Rating rounding (decided):** the card shows `sum/count` rounded half-up to one decimal; `rating_avg` is stored at two decimals; the `minRating` filter compares against the same one-decimal value the card shows (`round(rating_sum::numeric / rating_count, 1) >= :min`), so a tutor never shows "4.5" yet fails `minRating=4.5`. T06 implements this and tests a 4.45 average.

**Booking (T03).**
- §a.3: `platform_admin` and `system` may cancel `requested` as well as `accepted` before the start (block, suspension and close sweeps). Guard: `now < starts_at`.
- `allowed_actions` never returns `post_note`. The DTO builder adds it, for a student or tutor viewer only, from `can_post_note(effective_state(...))` evaluated at the same `now`. Parents never get it. `can_post_note` trusts its effective-state argument: `requested` is live only while `now < starts_at`.
- `allowed_actions` has no suspended or closed input. The builder removes tutor write actions when the tutor profile is suspended or closed (CB-7).
- Notes are allowed strictly before `ends_at + NOTE_POST_GRACE`, the instant reviews open (`review_open_at`).
- Slots: a rule that starts inside the spring-forward gap starts at the jump instant, and that night's step grid re-anchors there. "Offers nothing in the gap" means nothing before the jump. A repeated hour offers no slot whose start or end label is ambiguous.
- All instants passed to `core.booking` are timezone-aware; a naive datetime is a `ValueError`.
- An active block withholds only `accept` from the tutor's allowed actions; a review stays allowed under an active block (O10 is silent; confirmed here as deliberate: the block ends future contact, not the right to rate a past session).
- THREAT-MODEL SC-17's "more than 48 h" means `>= 48 h`, as in §a.3 and O23.

**Booking party in DTOs (T04, SC-9).** `BookingDTO.requestedBy`, `cancelledBy` and `completedBy` may be `"parent"` in the type, but for a tutor viewer the builder maps `"parent"` to `"student"`: a tutor never learns that a parent link exists.

**Report snapshots and admin notes (T04, §a.5).** `ReportDetailDTO.snapshot` stays `dict[str, JsonValue]`, built through one function with a per-`targetType` key allowlist (tutor_profile: card fields and bio; review: stars and text; review_reply: body; booking: the `AdminBookingSummaryDTO` fields; booking_note: author party and body). A student-authored note in an admin response carries the party label, never the student's name.

### i.5 Clarifications settled during Wave 2 (2026-10-26)

Written by the lead from the T05/T06/T07/T08 task reviews.

**Directory (T06).** The keyset cursor has four slots `(rank_score, first_listed_at_missing, first_listed_at, id)`, ordered `rank_score DESC, first_listed_at ASC NULLS LAST, id`, which is the `ix_tutor_profiles_directory` order; the §b.2 three-slot description is superseded. Later pages add a redundant `rank_score <= :k_rank` bound so the index can seek. The §e.3 query budget counts repository statements only; SP2 and T4 add one verified-email lookup. `ix_tutor_profiles_rated` cannot serve the `round(sum/count, 1)` predicate of §i.4 and is not used by the directory. New 422 codes: `invalid_area`, `invalid_day`, `invalid_cursor`, `invalid_profile`, `invalid_subjects`, `invalid_modes`, `invalid_rules`, `invalid_public_name`, `contact_details_not_allowed`; `not_a_teacher` is 403; a hidden tutor returns the same `not_found` body everywhere. The unverified-email refusal is 403 (SPEC §0), not the 409 THREAT-MODEL SC-15 names.

**Reinstatement (decided, T10).** §a.3 "reinstatement restores nothing" applies to grants and counters only. A profile reinstated from `suspended` that has never been approved (`first_listed_at IS NULL`) returns to `pending_review`, never directly to `listed` (row 5a: an admin approves before any listing). A profile that was listed before is reinstated to `listed`.

**Edge indexing (T08).** The nginx map is `~*^/tutors([/?]|$)`: `$request_uri` includes the query string and the router ignores case, so the literal `~^/tutors(/|$)` of rev 3 left `/tutors?subject=x` without `noindex`. The worker stores only `200` responses that say `public` and set no cookie, with its own 60 s TTL; the cache key is the page-origin public P2 URL, shared with the browser's own P2 call; 404s are not cached, so each random-UUID card view costs one backend query (the WAF rule is the only limit). The upstream request on the cacheable branch is built from scratch (no cookie, no authorization). Known limit (§i.3): odd spellings of the path (`/TUTORS/<id>` on Cloudflare, percent-encoded `/%74utors/<id>` on self-host) skip the worker header until the G-16/G-17 canonical-path guard lands (assigned to the card-page task, with a vitest).

**Notifications and email (T07).** `send_after_commit(notices, *, service, transport)`. The acting user gets no inbox notice for their own action. The delivery job re-reads the preference at send time and skips with `preference_off`; the daily cap is serialised with an advisory lock (`pg_advisory_xact_lock`) so replicas cannot overshoot. The moderation notice key carries a text revision (`{kind}:{id}:{outcome}:{revision}`). Skipped outbox rows keep `attempts = 0` (`attempts` counts send attempts). Booking accepted and declined emails go to the student and parent audiences only. A platform admin has no inbox; the durable record of a report is X-07. The student inbox labels, the push click router and the platform-admin report push for the eight types belong to T23. The router-level proof that a failing inbox write cannot undo a state change belongs to T13.

**Outcomes (T05).** A student is an eligible member only if their FIRST email verification was at or before their first session (`email_verified_at <= S`); a later verification does not move it, so the verification timestamp must be kept at first set (T09 changes `mark_email_verified`). All window, expiry and hold comparisons are made on UTC instants, never on wall-clock time, because Cairo's clocks repeat an hour on 29 October. The two residuals the review found (the 90-day hold does not hide an opt-out forever; grades are not frozen at the close instant) are recorded in ADR-T04 as accepted risks R8 and R9.
