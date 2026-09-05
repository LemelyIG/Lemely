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

Five things are genuinely outstanding.

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
4. **Teachers and parents have no inbox.** `at_risk_alert` is addressed to
   both (`lemely/web/routers/student.py:867`), and neither portal has a screen
   to read it in. `pushDecision.ts` says so and falls back to `/`.
5. **The teacher announcements screen still describes a phase that has
   passed.** Its header tells a teacher students cannot see announcements and
   no notification is sent. Both statements are now false.

This design closes all five.

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

The comparison uses the same clock the repository uses, so a post dated one
second ago and one dated one second ahead do not disagree with the visibility
gate about which they are.

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

Both are daily, anchored to a civil hour in `Africa/Cairo` (`xp_repo
.DEFAULT_ZONE`), and both need no new bookkeeping table.

### Idempotency is the existing unique index

A daily job must fire once per recipient per civil day even though the sweep
loop runs every minute. That is already solved: migration 0018's partial unique
index on `(user_id, type, dedupe_key)` means a job that passes **the civil date
itself** as the dedupe key sends once and every later attempt that day comes
back `outcome=duplicate, push_allowed=False`. No "last sent at" column, no
cursor, no lock. The job simply asks "is it past the trigger hour" and lets the
index answer "has this already gone out".

This corrects a docstring. `NotificationService.create` currently offers
`study_plan_reminder` as its example of a type with *no* natural key — "two
`study_plan_reminder` rows a week apart are two real reminders". Under this
design it has one, and so does `streak_warning`. The docstring is rewritten,
for the reason `_notify_audience` already gives about a different comment: a
comment the code disproves is worse than no comment.

### `streak_warning`

**Trigger.** Local civil time at or past 19:00.

**Recipients.** `streaks` rows with `current_length >= 1` and
`last_active_on < today`. Streaks belong to students by construction — XP is
only ever awarded to one — so no role filter is needed.

**Key.** `dedupe_key = today.isoformat()`, one per student per day.

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

**Trigger.** Local civil time at or past 08:00.

**Recipients.** `study_plan_sessions` joined to their plan where
`StudyPlan.superseded_at IS NULL`, `session.date = today`, and
`session.completed_at IS NULL`.

**Key.** `dedupe_key = str(session_id)`, so each scheduled session prompts
exactly once, ever — including across a day boundary or a restart.

**Payload.** `{"sessionId": ..., "subjectCode": ..., "topic": ...}`.
Destination `/student/plan/{subjectCode}/session/{sessionId}`.

**Copy.** Title `Today's study session`; body the topic and duration, e.g.
`Algebraic fractions · 40 min`. A pointer to the session, not a summary of it.

**Volume, stated rather than discovered later.** A plan is single-subject, so a
student studying three subjects with a session dated today receives three
notifications at 08:00. If that proves too much, the collapse is a one-line
change of shape — group the day's sessions per student, key on
`today.isoformat()`, name the first topic and the remaining count, and send the
reader to the first session — and it is deliberately *not* done now, because a
per-session key is the one that also survives a plan being regenerated
mid-week.

## 3. The runner

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

**A per-day memo, for cost and not for correctness.** After 19:00 the streak
query would otherwise run every 60 seconds until midnight, and every one of
those runs after the first would do real work only to have the unique index
throw it away. Each daily job therefore remembers the last civil date it
completed and skips until the date changes. This is an optimisation and is
labelled as one: correctness comes from the dedupe index, which is also what
keeps two replicas — each with its own memo — from double-sending.

**Cloud Run caveat, documented rather than hidden.** Timely delivery needs
`--min-instances=1`. At zero instances the container is not running and no
sweep happens; the first request after scale-up sweeps and delivers late. For
an announcement that is correct-but-late. For a 19:00 streak warning it may
mean no warning at all that day, since the memo and the dedupe key are both
scoped to the civil date. `docs/deployment.md` will say exactly that rather
than implying a guarantee the platform does not give.

## 4. VAPID keys

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

## 5. Teacher and parent inboxes

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

## 6. Copy

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

## 7. Testing

**pytest**

Announcements:

- A future `publishAt` produces no notification at create time.
- A `NULL` or past `publishAt` notifies at create time, as today.
- The job claims a due row, fans out to the full audience, and stamps it.
- It ignores rows already stamped and rows not yet due.
- A run interrupted between send and stamp, re-run, produces no second inbox
  row and no second push — the direct test of the stamp-after-send choice.
- Two concurrent runs do not both claim one row.

Streaks:

- A student inactive today with a live streak is warned once at 19:00, and a
  second and third pass in the same day send nothing.
- A student who earned XP today is not warned.
- A student with `current_length == 0` is not warned.
- The freeze-available and no-freeze bodies differ, and each names the real
  streak length.
- Before 19:00 local, nothing is sent — including for a caller whose own
  wall-clock hour differs from `Africa/Cairo`.
- `streak_warning: false` in preferences suppresses the row entirely.

Study plans:

- An incomplete session dated today is reminded once; a repeat pass sends
  nothing.
- A completed session, a session on another date, and a session on a
  superseded plan are all skipped.
- Three subjects with a session each today produce three notifications — the
  volume is asserted, not left to be discovered in production.
- `study_plan_reminder: false` in preferences suppresses the row.

Keys:

- `push-keygen` output round-trips: the generated pair signs a header
  `VapidPushTransport.authorization_header` accepts and that verifies against
  the public key.

**vitest**

- Both new inbox screens: loading, empty, error, loaded, mark-all-read.
- `destinationFor` routes all five notification types.

**Playwright**

- `/teacher/notifications` and `/parent/notifications` render for their own
  role and 404 for others.

## Out of scope

- Announcement attachments. There is still no column and no storage wiring.
- Batching or queueing the fan-out. It stays sequential; a class is tens of
  students and a school is hundreds.
- Per-user timezones. Every civil-date and trigger-hour calculation uses
  `DEFAULT_ZONE`, exactly as the streak itself already does.
