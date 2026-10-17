# Push notifications: finishing delivery

**Date:** 2026-09-05
**Status:** Approved, ready for an implementation plan
**Branch:** `feat/push-notification-delivery`

## Why this exists

The web-push stack in this repo is already written end to end. What is missing
is smaller and more specific than "implement push notifications" suggests, and
naming the gap precisely is most of the value of this document.

What already exists:

| Piece | Where |
| --- | --- |
| VAPID transport (RFC 8292 header, RFC 8030 TTL, 404/410 expiry) | `lemely/web/push.py` |
| Subscription storage, preferences, quiet hours, dedupe | `lemely/db/notification_repo.py` |
| The single notification seam | `lemely/web/notify.py` |
| `GET /notifications/push/config`, `POST` subscribe | `lemely/web/routers/notifications.py` |
| Service worker and its pure decision half | `web/src/sw.ts`, `web/src/lib/push/pushDecision.ts` |
| Enable/permission state machine | `web/src/lib/push/pushEnable.ts` |
| Page↔worker content handshake | `web/src/lib/push/pushClientBridge.ts` |
| Notification preferences UI, all five types | `web/src/portals/settings/NotificationSettings.tsx` |
| Announcement fan-out to the audience | `lemely/web/routers/announcements.py:164` |
| Student announcement inbox | `lemely/web/routers/student_announcements.py`, `web/src/portals/student/screens/Notifications.tsx` |

Six things are genuinely outstanding.

1. **No VAPID keys are configured anywhere.** Every field of `PushSettings`
   defaults to `None`, so `VapidPushTransport.available` is `False` and every
   push is suppressed with `transport_unavailable`. No real push has ever been
   delivered by this system.
2. **A future-dated announcement notifies immediately.** `_notify_audience`
   runs unconditionally at create time, but `AnnouncementRepo._is_visible`
   hides the post until `publish_at`. A student would receive a push, tap it,
   and find nothing. There is no scheduler.
3. **`streak_warning` and `study_plan_reminder` are never sent.** Both are
   `NotificationType` members with their own preference column and their own
   toggle in the settings UI, and nothing anywhere calls `notify_safely` with
   either. A student can opt out of a notification that does not exist.
4. **Every civil-date and civil-time calculation is in `Africa/Cairo`.** Quiet
   hours, streak days and XP daily caps all assume one launch market. A
   student outside it has quiet hours in the wrong window, and once §2 ships
   would get a "nothing logged today" notification in the middle of their
   night.
5. **Teachers and parents have no inbox.** `at_risk_alert` is addressed to
   both (`lemely/web/routers/student.py:867`), and neither portal has a screen
   to read it in. `pushDecision.ts` says so and falls back to `/`.
6. **The teacher announcements screen still describes a phase that has
   passed.** Its header tells a teacher students cannot see announcements and
   no notification is sent. Both statements are now false.

This design closes all six.

## 1. Deferred announcement notification

### Schema

One migration adds a nullable column to `announcements`:

```
notified_at TIMESTAMPTZ NULL
```

plus a partial index over `(publish_at)` `WHERE notified_at IS NULL`, which is
the only shape the sweeper's query needs and stays tiny because the vast
majority of rows are stamped.

`notified_at` means *fan-out for this row completed*. `NULL` means it has not.
It is deliberately not a boolean: the timestamp answers "when did this go out",
which is the question an operator investigating a missed notification asks.

### Create path

In `lemely/web/routers/announcements.py`:

- `publish_at` is `NULL` or already in the past — fan out immediately, as
  today, then stamp `notified_at`.
- `publish_at` is in the future — do not fan out. Leave `notified_at` `NULL`
  and let the sweeper claim it.

`publish_at` is an absolute instant, not a civil time, so §3's per-user zones
do not touch this comparison. A teacher scheduling a post for Thursday 09:00
schedules one moment, and every student's copy is released at that moment.

### The job

`publish_due_announcements`, in `lemely/web/scheduled_notifications.py`:

1. Claim due rows:
   `WHERE notified_at IS NULL AND publish_at IS NOT NULL AND publish_at <= now`
   with `FOR UPDATE SKIP LOCKED LIMIT n`. `SKIP LOCKED` is what makes two
   replicas safe without a lock table.
2. Fan out each claimed row through the existing `_notify_audience` logic,
   which moves out of the router into this module so both callers share one
   implementation.
3. Stamp `notified_at` **after** the fan-out.

**Stamping after the send is the deliberate choice.** A crash between the send
and the stamp re-runs the row on the next pass, and that re-run is harmless:
`_notify_audience` passes `dedupe_key=str(announcement_id)`, migration 0018's
unique index on `(user_id, type, dedupe_key)` rejects the second insert, and
`NotificationService.create` returns `outcome=duplicate` with
`push_allowed=False` — so neither a duplicate inbox row nor a duplicate push
can occur. Stamping before the send would instead silently lose the whole
audience's notification on the same crash. Idempotency here is a property the
existing code already guarantees, not one this design has to add.

## 2. The two engagement notifications

Both are daily and anchored to a civil hour in **the recipient's own zone**
(§3), and both need no new bookkeeping table.

### Idempotency is the existing unique index

A daily job must fire once per recipient per civil day even though the sweep
loop runs every minute. That is already solved: migration 0018's partial unique
index on `(user_id, type, dedupe_key)` means a job that passes **that
recipient's own civil date** as the dedupe key sends once and every later
attempt that day comes back `outcome=duplicate, push_allowed=False`. No "last
sent at" column, no cursor, no lock. The job asks only "is it past the trigger
hour where this user is" and lets the index answer "has this already gone out".

This corrects a docstring. `NotificationService.create` currently offers
`study_plan_reminder` as its example of a type with *no* natural key — "two
`study_plan_reminder` rows a week apart are two real reminders". Under this
design it has one, and so does `streak_warning`. The docstring is rewritten,
for the reason `_notify_audience` already gives about a different comment: a
comment the code disproves is worse than no comment.

### `streak_warning`

**Trigger.** The recipient's local civil time at or past 19:00.

**Recipients.** `streaks` rows with `current_length >= 1` and
`last_active_on < today`, where `today` is that user's own civil date. Streaks
belong to students by construction — XP is only ever awarded to one — so no
role filter is needed.

**Key.** `dedupe_key = <that user's civil date>.isoformat()`, one per student
per their own day.

**Payload.** `{"streakLength": n, "freezeAvailable": bool}`. Destination
`/student/profile`, the S-31 screen the streak lives on.

**Copy, and the principle it has to satisfy.** `Profile.tsx:41-45` states the
streak is "offered, never used as leverage — no countdown to losing it, no red,
no 'don't break it now!'". A 19:00 warning is the exact shape that sentence
refuses, so the constraint moves into the wording rather than cancelling the
feature:

- Title: `Nothing logged today`
- Body, freeze available: `A freeze will cover today. Your 12-day streak stays.`
- Body, no freeze: `Your 12-day streak ends if today stays empty.`

Each states the situation once. No exclamation, no countdown, no second
sentence stacking urgency on the first.

**Why it fires even when a freeze would cover the day** (the choice taken over
warning only on real loss): a freeze is consumed silently by `_resolve_gap`, so
a student who is never told burns freezes without knowing they had them. The
kinder message is the one that says a freeze is being spent, which is why the
two bodies differ rather than the recipient set narrowing.

### `study_plan_reminder`

**Trigger.** The recipient's local civil time at or past 08:00.

**Recipients.** `study_plan_sessions` joined to their plan where
`StudyPlan.superseded_at IS NULL`, `session.date` equals that user's civil
today, and `session.completed_at IS NULL`.

**Key.** `dedupe_key = str(session_id)`, so each scheduled session prompts
exactly once, ever — including across a day boundary or a restart.

**Payload.** `{"sessionId": ..., "subjectCode": ..., "topic": ...}`.
Destination `/student/plan/{subjectCode}/session/{sessionId}`.

**Copy.** Title `Today's study session`; body the topic and duration, e.g.
`Algebraic fractions · 40 min`. A pointer to the session, not a summary of it.

**Volume, stated rather than discovered later.** A plan is single-subject, so a
student studying three subjects with a session dated today receives three
notifications at 08:00. If that proves too much, the collapse is a one-line
change of shape — group the day's sessions per student, key on their civil
date, name the first topic and the remaining count, and send the reader to the
first session — and it is deliberately *not* done now, because a per-session
key is the one that also survives a plan being regenerated mid-week.

## 3. Per-user timezones

### What moves and what does not

Personal facts move to the user's own zone. Shared facts stay global.

| Calculation | Zone | Why |
| --- | --- | --- |
| Quiet hours (`NotificationService.create`) | user | Whose night it is, is a personal fact. |
| `streak_warning` / `study_plan_reminder` trigger hour | user | Same. |
| `XpService.award` → `awarded_on`, and the daily cap | user | The cap is per student. |
| Streak days (`streak`, `_resolve_gap`) | user | A streak should roll over at the student's own midnight. |
| At-risk assessment `today` (`student.py:860`) | the assessed student | It windows that student's own work. |
| Profile week window (`week_bounds`) | **global** | See below. |
| Leaderboard week and `today` | **global** | See below. |

**Why the two week windows stay global.** `week_bounds` is deliberately the
single definition of "this week" in the codebase (`xp_repo.py:130-144`): D5.13
§2 records that a second copy "would let the profile screen and the leaderboard
disagree about a fact the student can switch between in one tap". A leaderboard
is worse still — it is a *shared* artifact, and summing two students' XP over
two different weeks makes the ranking mean nothing. Both therefore keep
`DEFAULT_ZONE`, and `leaderboard_repo` gains a comment saying so rather than
being left to look like an oversight.

**The seam this creates, stated plainly.** In `XpService.profile` the streak
and the 28-day calendar use the student's civil today while the week window
uses the global one. For a student far from Cairo, near midnight, the week
window can be off by a day relative to their own date. That is the accepted
cost of keeping one shared week; it is bounded at one day and it self-corrects
within hours.

**History is not rewritten.** `xp_events.awarded_on` rows already stored were
computed in `Africa/Cairo` and stay as they are. A zone applies forward only.
The visible consequence is bounded: a student who changes zone may see one
day-boundary in their calendar that reflects the old zone. Recorded here rather
than presented as exact.

### Schema

Migration adds two columns to `users`:

```
timezone              VARCHAR(64) NULL
timezone_is_explicit  BOOLEAN NOT NULL DEFAULT false
```

`timezone` `NULL` means never set and resolves to `DEFAULT_ZONE`, so the
migration is a no-op for every existing row and the deploy changes nobody's
behaviour. `timezone_is_explicit` records that the *user* chose it, which is
what stops auto-detect overwriting a deliberate choice.

### Resolution

One helper, beside `civil_date_in_zone` in `lemely/db/xp_repo.py`:

```python
def resolve_zone(name: str | None) -> ZoneInfo
```

Returns `DEFAULT_ZONE` for `NULL`, and also for a name `ZoneInfo` cannot
resolve — logging a warning in that case. **It never raises.** A stored zone
that a later tzdata drop retires must not be able to fail a student's XP award;
falling back to the launch zone is wrong by an hour or two, and throwing is
wrong by the whole feature.

A small `UserZoneReader` collaborator is injected into `XpService` and
`NotificationService`. It reads `users.timezone` for a user id and memoises
within its own lifetime, which is one request. The three services keep their
existing `zone` constructor argument as the fallback the reader defers to, so
every existing test that pins a zone keeps working unchanged.

### Setting it

**Auto-detect.** The client sends
`Intl.DateTimeFormat().resolvedOptions().timeZone` at app boot. The server
stores it only when `timezone_is_explicit` is false, so a deliberate choice is
never silently undone by opening the app on a plane.

**Explicit.** A picker in `web/src/portals/settings/ProfileSettings.tsx` sets
the zone and `timezone_is_explicit = true`. Clearing it back to "follow this
device" sets `timezone_is_explicit = false` and lets auto-detect resume.

**Endpoint.** `PUT /me/timezone`, taking `{ "timezone": str, "explicit": bool }`.
On the `me` router rather than `student-profile`, because a timezone applies to
every role — a teacher and a parent both receive `at_risk_alert` and both have
quiet hours.

**Validation.** The name must resolve through `ZoneInfo` and be at most 64
characters, else 422. An unvalidated string here would be stored once and then
degrade to `DEFAULT_ZONE` on every read forever, which looks like the feature
silently not working.

## 4. The runner

`create_app()` gains a `lifespan` (it has none today) that starts one asyncio
task. Each tick calls the three jobs — `publish_due_announcements`,
`warn_streaks`, `remind_study_plans` — each wrapped individually, so a job that
throws is a logged warning and the other two still run.

New settings section:

```toml
[notifications]
sweeper_enabled = true
sweep_poll_seconds = 60
streak_warning_hour = 19
study_plan_reminder_hour = 8
```

`sweeper_enabled` is `false` under test, so the suite never races a background
task.

### Firing a per-user hour without scanning every user

The two daily jobs no longer have a single global trigger moment. Each pass:

1. `SELECT DISTINCT timezone FROM users WHERE timezone IS NOT NULL`, plus the
   implicit `DEFAULT_ZONE` bucket that covers every `NULL`. This list is tiny —
   distinct zones, not users.
2. Keep the zones whose local civil time is at or past the trigger hour.
3. Query candidates restricted to those zones
   (`COALESCE(users.timezone, '<default>') = ANY(:zones)`).
4. Key each notification on that user's own civil date.

So the work is proportional to the number of *zones in use*, not to the user
count, and a user in a zone that has not reached the hour is never loaded.

**A per-zone memo, for cost and not for correctness.** After 19:00 in a given
zone the query for that zone would otherwise repeat every 60 seconds until
midnight, doing real work only for the unique index to discard it. Each daily
job therefore remembers the last civil date it completed *per zone* and skips
that zone until its date changes. This is an optimisation and is labelled as
one: correctness comes from the dedupe index, which is also what keeps two
replicas — each with its own memo — from double-sending.

**Cloud Run caveat, documented rather than hidden.** Timely delivery needs
`--min-instances=1`. At zero instances the container is not running and no
sweep happens; the first request after scale-up sweeps and delivers late. For
an announcement that is correct-but-late. For a 19:00 streak warning it may
mean no warning at all that day, since the memo and the dedupe key are both
scoped to the user's civil date. `docs/deployment.md` will say exactly that
rather than implying a guarantee the platform does not give.

## 5. VAPID keys

### `lemely push-keygen`

A new flat click command, matching the repo's existing flat command style
(`estimate-cost`, `parse-mark-schemes`), not a subgroup. It generates a P-256
keypair and prints:

- the base64url public key (uncompressed point, 65 bytes),
- the base64url private scalar (32 bytes),
- a paste-ready `[push]` block.

It writes no file. The private key never touches disk through this tool, so
there is no half-written secret to forget about.

### Configuration and deployment

- `lemely.toml.example` gains a commented `[push]` section.
- `.github/workflows/deploy.yml` gains three Cloud Run env vars:
  `LEMELY_PUSH__VAPID_PUBLIC_KEY` from a repository **variable** (it is handed
  to every browser and is not a secret), `LEMELY_PUSH__VAPID_PRIVATE_KEY` from
  a repository **secret**, and a literal `LEMELY_PUSH__VAPID_SUBJECT`.
- An unset secret renders as the empty string and is tolerated, exactly as
  `LEMELY_EMAIL__API_KEY` already is: the deploy succeeds and push simply stays
  unavailable. That is what lets this land before the secret is registered.

### Documentation and validation

`docs/push-notifications.md` covers generating, placing, verifying, and
rotating. It states plainly that **rotating the keypair invalidates every
stored subscription** — the `applicationServerKey` is baked into each
subscription, so every browser must re-subscribe. That is the one fact that
makes rotation an event rather than a chore.

`lemely doctor` gains a push check: keys present or absent, and whether the
transport reports itself available.

## 6. Teacher and parent inboxes

Per-portal screens, not a shared one. Only `at_risk_alert` ever reaches these
two roles, and the same alert reads differently to each: a teacher sees a
student they teach, a parent sees their own child.

- **Teacher** — `web/src/portals/teacher/screens/Notifications.tsx`, route
  `/teacher/notifications`, a nav entry carrying the unread count. A row links
  to `/teacher/students/:studentId`, taken from `payload.studentId`.
- **Parent** — `web/src/portals/parent/screens/Notifications.tsx`, route
  `/parent/notifications`, rows linking to `/parent/children/:childId`.

Both sit on the existing role-agnostic `useNotifications` and
`useMarkAllNotificationsRead` hooks — `tests/test_web_notifications.py`
already asserts every role can open its own inbox. Shared chrome is limited to
components that already exist (`QueryState`, `ListSkeleton`, `EmptyState`); the
student screen is not extracted or refactored.

`pushClientBridge.ts`'s `destinationFor` gains the four types it does not
currently route: `at_risk_alert` to the viewer's own role inbox,
`streak_warning` to `/student/profile`, `study_plan_reminder` to that session's
plan page. `grade_ready` keeps its deliberate lack of a specific destination.
`DEFAULT_PUSH_URL` stays `/`: it is the fallback for when no page answered the
worker at all, and `/` routes by role, so it cannot 404 for whoever received
the push. Only the comment justifying it — which currently says neither portal
has an inbox screen — is corrected.

## 7. Copy

Removed, because each states something that is no longer true:

- `web/src/portals/teacher/screens/Announcements.tsx:196-201` — the header
  sentence naming students who cannot see announcements and a notification that
  is not sent.
- The same file's module doc comment (~lines 55-67), which describes the
  student surface and the delivery path as a later phase's work.
- `web/src/lib/teacherTypes.ts:37-38` — "Announcement endpoints remain a later
  P3.8 chunk's to add".
- `web/src/lib/teacherTypes.ts:1074-1076` — "`publishAt` is stored but never
  read ... never imply it will fire". After this change `publishAt` both gates
  visibility and schedules the notification, so the replacement says that.

**Explicitly kept:** the `unavailable` state in
`web/src/portals/settings/NotificationSettings.tsx` and `{ kind: "unavailable" }`
in `web/src/lib/push/pushEnable.ts`. These are not phase markers. They are the
correct runtime answer whenever VAPID keys are absent, which is every developer
machine and every CI run, and `pushEnable.ts` deliberately orders availability
ahead of browser support so a reader is not sent on an errand that changes
nothing. Deleting them would put an enable button that silently fails in front
of every developer. They stop appearing in staging and production the moment
keys are configured, which is the intended behaviour.

`CHANGELOG.md` and `DELIVERY.md` mentions of the unavailable transport are a
historical record of what shipped when. They are appended to, not rewritten.

## 8. Testing

**pytest — announcements**

- A future `publishAt` produces no notification at create time.
- A `NULL` or past `publishAt` notifies at create time, as today.
- The job claims a due row, fans out to the full audience, and stamps it.
- It ignores rows already stamped and rows not yet due.
- A run interrupted between send and stamp, re-run, produces no second inbox
  row and no second push — the direct test of the stamp-after-send choice.
- Two concurrent runs do not both claim one row.

**pytest — streaks**

- A student inactive today with a live streak is warned once at their 19:00,
  and a second and third pass in the same day send nothing.
- A student who earned XP today is not warned.
- A student with `current_length == 0` is not warned.
- The freeze-available and no-freeze bodies differ, and each names the real
  streak length.
- `streak_warning: false` in preferences suppresses the row entirely.

**pytest — study plans**

- An incomplete session dated today is reminded once; a repeat pass sends
  nothing.
- A completed session, a session on another date, and a session on a
  superseded plan are all skipped.
- Three subjects with a session each today produce three notifications — the
  volume is asserted, not left to be discovered in production.
- `study_plan_reminder: false` in preferences suppresses the row.

**pytest — timezones**

- `resolve_zone` returns `DEFAULT_ZONE` for `NULL`, for `""`, and for an
  unresolvable name, and never raises.
- Two students in `Africa/Cairo` and `America/Los_Angeles`, awarded XP at one
  UTC instant that falls on different civil dates for them, get different
  `awarded_on` values.
- Quiet hours are evaluated in the recipient's zone, not the server's.
- One sweep pass warns the Cairo student and not the Los Angeles one when only
  Cairo has passed 19:00, and warns Los Angeles eight hours later in the same
  process.
- Each is keyed on their own civil date, so a pass spanning a date boundary in
  one zone but not the other double-sends to neither.
- The leaderboard week is identical for both students — the direct regression
  test for the invariant §3 refuses to break.
- `PUT /me/timezone` rejects a non-IANA name and an over-length string with
  422.
- A non-explicit write does not overwrite a zone the user set explicitly; an
  explicit write does.
- A user whose zone is set does not have their existing `awarded_on` rows
  changed.

**pytest — keys**

- `push-keygen` output round-trips: the generated pair signs a header
  `VapidPushTransport.authorization_header` accepts and that verifies against
  the public key.

**vitest**

- Both new inbox screens: loading, empty, error, loaded, mark-all-read.
- `destinationFor` routes all five notification types.
- The timezone picker sends `explicit: true`, and "follow this device" sends
  `explicit: false`.

**Playwright**

- `/teacher/notifications` and `/parent/notifications` render for their own
  role and 404 for others.

## Out of scope

- Announcement attachments. There is still no column and no storage wiring.
- Batching or queueing the fan-out. It stays sequential; a class is tens of
  students and a school is hundreds.
- Re-computing historical `awarded_on` dates against a user's new zone. See
  §3 — history stands as recorded.
- A per-user zone for the leaderboard or the profile week. Deliberately
  refused in §3, not merely deferred.
