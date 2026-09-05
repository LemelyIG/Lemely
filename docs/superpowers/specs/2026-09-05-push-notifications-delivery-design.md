# Push notifications: finishing delivery

**Date:** 2026-09-05
**Status:** Approved, ready for an implementation plan

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
| Notification preferences UI | `web/src/portals/settings/NotificationSettings.tsx` |
| Announcement fan-out to the audience | `lemely/web/routers/announcements.py:164` |
| Student announcement inbox | `lemely/web/routers/student_announcements.py`, `web/src/portals/student/screens/Notifications.tsx` |

Four things are genuinely outstanding.

1. **No VAPID keys are configured anywhere.** Every field of `PushSettings`
   defaults to `None`, so `VapidPushTransport.available` is `False` and every
   push is suppressed with `transport_unavailable`. No real push has ever been
   delivered by this system.
2. **A future-dated announcement notifies immediately.** `_notify_audience`
   runs unconditionally at create time, but `AnnouncementRepo._is_visible`
   hides the post until `publish_at`. A student would receive a push, tap it,
   and find nothing. There is no scheduler.
3. **Teachers and parents have no inbox.** `at_risk_alert` is addressed to
   both (`lemely/web/routers/student.py:867`), and neither portal has a screen
   to read it in. `pushDecision.ts` says so and falls back to `/`.
4. **The teacher announcements screen still describes a phase that has
   passed.** Its header tells a teacher students cannot see announcements and
   no notification is sent. Both statements are now false.

This design closes all four.

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

### The sweeper

New module `lemely/web/announcement_publisher.py`. One public function that
takes the services it needs and does one pass:

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

### The runner

`create_app()` gains a `lifespan` (it has none today) that starts one asyncio
task. The task sleeps, sweeps, and logs; every pass is wrapped so a failing
sweep is a logged warning and the loop survives to the next tick.

New settings section:

```toml
[announcements]
publish_poll_seconds = 60
publish_sweeper_enabled = true
```

`publish_sweeper_enabled` is `false` under test, so the suite never races a
background task.

**Cloud Run caveat, documented rather than hidden.** Timely delivery needs
`--min-instances=1`. At zero instances the container is not running and no
sweep happens; the first request after scale-up sweeps and delivers late. That
is correct-but-late, not broken, and `docs/deployment.md` will say exactly
that rather than implying a guarantee the platform does not give.

## 2. VAPID keys

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

## 3. Teacher and parent inboxes

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

`pushClientBridge.ts` maps an `at_risk_alert` to the viewer's own role inbox.
`DEFAULT_PUSH_URL` stays `/`: it is the fallback for when no page answered the
worker at all, and `/` routes by role, so it cannot 404 for whoever received
the push. Only the comment justifying it — which currently says neither portal
has an inbox screen — is corrected.

## 4. Copy

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

## 5. Testing

**pytest**

- A future `publishAt` produces no notification at create time.
- A `NULL` or past `publishAt` notifies at create time, as today.
- The sweeper claims a due row, fans out to the full audience, and stamps it.
- The sweeper ignores rows already stamped and rows not yet due.
- A sweep interrupted between send and stamp, re-run, produces no second inbox
  row and no second push — the direct test of the stamp-after-send choice.
- Two concurrent sweeps do not both claim one row.
- `push-keygen` output round-trips: the generated pair signs a header
  `VapidPushTransport.authorization_header` accepts and that verifies against
  the public key.

**vitest**

- Both new inbox screens: loading, empty, error, loaded, mark-all-read.
- `pushClientBridge` routes an `at_risk_alert` to the right role inbox.

**Playwright**

- `/teacher/notifications` and `/parent/notifications` render for their own
  role and 404 for others.

## Out of scope

- `streak_warning` and `study_plan_reminder` exist in `NotificationType` and in
  the preferences table but nothing ever sends them. That is a real gap and a
  separate piece of work.
- Announcement attachments. There is still no column and no storage wiring.
- Batching or queueing the fan-out. It stays sequential; a class is tens of
  students and a school is hundreds.
