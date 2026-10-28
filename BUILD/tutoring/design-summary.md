# Tutoring marketplace — design summary (awaiting LOCK)

Full rationale and rejected options: `decision-log.md`. Facts: `recon.md`.

## Design
- **Who:** a tutor is a `tutor_profiles` row (1:1 with a `teacher` user). No new `Role`. Signup can make a school-less teacher who only tutors. A co-teacher is a peer with their own profile.
- **Onboarding:** profile (bio, subjects 0580/0606/0625, modes, city-level area, qualification note, optional evidence upload), then `platform_admin` approves before listing.
- **Directory:** public on the web, minimal card only (first name + initial, short bio, subjects, modes, city, rating + count; `noindex` until the tutor opts in). Everything else needs login. No prices; fees are agreed outside Lemely.
- **Discovery:** filters for subject, min rating, mode, area and availability. Bayesian ranking; under 3 reviews shows 'New'. Keyset paging.
- **Booking:** the student, or a linked parent for the child, requests a slot. The tutor accepts or declines. A Postgres exclusion constraint blocks double-booking. Times are Africa/Cairo, stored UTC. Virtual shows the meeting link after accept; in-person shows city-level area until accept. Cancel up to 24h before; the tutor marks no-shows. A booking-scoped notes thread is visible to the student, tutor and linked parents. Inbox notifications plus a new booking-event email path.
- **Reviews:** one per completed booking, by that student. Text is moderated before it goes public. The tutor gets one reply, and edits close after 14 days.
- **Student data:** the student grants a tutor access to all subjects until revoked. Derived analytics only (grades, predictions, weaknesses, trend, at-risk, engagement); no raw scripts. Revocation applies on the next read. Every tutor read is audit-logged and visible to the student. Linked parents are notified of grants and bookings but cannot act on grants.
- **Outcomes on a tutor profile:** an ordered A*..G stacked bar plus a 'change in grade while with this tutor' figure. k >= 5 per tutor and subject, students counted by default with a notice and one-tap opt-out, n shown, table alternative. Insufficient-data state below k. The pie chart is dropped because grades are ordinal.
- **Delivery:** all of the above, in dependency waves.

## Open risks
1. **Child safety (compounded).** A minor alone can grant indefinite, all-subject access (D3, D3b). Their parent is only told (D4). Free-text notes thread (D4b) and in-person sessions have no guardian approval, and moderation is reactive. Each choice was argued against and the user decided. Together they are the weakest point of the design. Suggested cheap compensating controls, not yet decided: show the grant-and-audit log to linked parents read-only, and add a one-line safety notice to every first booking.
2. **Public tutor PII.** Minimal card plus `noindex` limits it. Real names are first name + initial only.
3. **Outcome stats mislead.** 'Change in grade' implies cause. Marks are about 70-84% accurate per DELIVERY §5.1, so small differences are noise. Mitigated by wording, k >= 5 and the caveat, not eliminated.
4. **Default-on counting of minors** in outcome stats is weaker than consent.
5. **Scope.** Parent booking is the first parent write action, booking email is a new seam, and `btree_gist` is a new Postgres extension. The wave plan has to isolate these.
6. **No scheduler.** Expiry, staleness and completion are all computed at read time. Nothing auto-cancels or reminds.
7. **Stale index and unverified facts** listed at the end of `recon.md`.

Reply **LOCK** to freeze these decisions, or name any to change.
