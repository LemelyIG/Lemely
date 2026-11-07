# Portal shell: one shared shell for student and teacher, from design A

Date: 2026-11-06
Branch: `design/student-home-variants`
Design source: the shell parts of `web/dev-previews/student-home-a.html` (`.as-*`) and
`web/dev-previews/student-home/variant-a.css`, `variant-a.js`, `shell.css`.
Related spec: `docs/superpowers/specs/2026-11-06-student-home-overview-design.md` (Overview page).

## Goal

Build one portal shell that both the student and the teacher portal use, styled as design A.
The shell is the frame around every page: sidebar, floating top bar, phone drawer, bottom tabs,
notifications panel, account panel and settings dialog.

## Decisions

| Question | Decision |
|---|---|
| Structure | One shared shell for both portals (not a student-only rebuild). |
| Teacher look | Teacher also moves to design A. |
| Baseline | Start from `origin/develop`, which already has the teacher settings dialog, bell dropdown, profile menu and the Abyss component kit. |
| Settings | A dialog opened by URL, the same way teacher works on `develop`. |
| Phones | Bottom tabs stay for both portals, as teacher has them. Logged as approved drift from the design. |
| Bell and avatar | Panels over the page, as in the design. |
| Styling | Tailwind v4 with the existing `@theme` tokens. |
| Fidelity | Same drift gate as the Overview spec: 0 differing pixels, or up to 15% with a written justification per difference. |

## Decisions (2026-11-06, plan)

1. Drawer breakpoint: below 1248px, as this spec says (design A switches at 1000px). The 1024px
   scenes differ from the design and are logged in the drift log.
2. Student nav: Tutors and Sessions are sidebar rows after Friends, styled like the others. Logged
   drift.
3. Streak gap: accepted. `HeaderStreak` goes with the old shell; the Overview hero restores the
   streak.
4. Avatar: squircle (kit `Avatar`, DESIGN.md §6), not design A's circle. Logged drift.
5. Phone bar: keep today's `BottomNav`, not design A's own 4-item bar.
6. The staged design A preview files are committed (signed WIP commit) before the merge.
7. Top bar is semi-translucent in both portals, like the landing page header (`brand.css`
   `.brand-header`): 86% of the bar's surface (light `surface-container-lowest`, dark
   `surface-container-high`) over a backdrop blur, solid when `backdrop-filter` is unsupported.
   The blur uses the app's single blur token `--blur-nav` (10px; the landing page uses 14px).
   Design A has the same rule (`variant-a.css`, commit `c880a54c`). User decision 2026-11-06.
8. Drift rule as built:
   - Gate scenes pass at 0 px, or up to 15% only with an entry whose `approved` is "yes".
   - Teacher frame, drawer, panel and settings scenes, and the student scenes at 1024px, are
     log-only: they have no cap but still need an approved entry.
   - Entries start "pending"; only the user approves.
   - Content scenes hide the shell chrome.
   - Teacher baselines are pinned to `aa533580` by per-key sidecars.

## 0. Baseline

This branch is 57 commits behind `origin/develop`. Merge `origin/develop` into
`design/student-home-variants` before any shell or Overview work. Resolve conflicts in favour of
`develop` for files this branch has not changed. Both specs are built on the merged tree.

## 1. Architecture

New folder `web/src/components/shell/`. It owns the frame. Each portal supplies its own content
through props; the shell has no student or teacher knowledge.

| Unit | Purpose | Source on `develop` |
|---|---|---|
| `PortalShell.tsx` | Layout: sidebar column, top bar, page well, drawer below 1248px, bottom tabs below the `sidebar` breakpoint, banners, skip link, edge swipe back, error boundary, route skeleton. | Layout parts of `portals/teacher/index.tsx` and `portals/student/index.tsx` |
| `ShellSidebar.tsx` | Design A sidebar frame: wordmark, nav list slot, labelled group slot, footer slot (primary action and user block). | Teacher `Sidebar`/`SidebarFooter` |
| `ShellTopBar.tsx` | Floating, semi-translucent bar: menu button, page title, primary action, bell, gear, avatar; breadcrumbs only when drilled in. | `TeacherTopBar` |
| `NotificationsPanel.tsx` | Bell panel: recent items, "Mark all read", empty state, footer link to the full page. | `portals/teacher/components/NotificationsMenu.tsx` |
| `AccountPanel.tsx` | Avatar panel: name, email, one detail line, a list of links, Sign out. | `portals/teacher/components/ProfileMenu.tsx`, `ProfileAvatar.tsx` |
| `TopBarSheets.tsx` | Phone sheets for the panels. | `portals/teacher/components/TopBarSheets.tsx` |

Moved, not copied: the teacher components above move into `components/shell/`, become
portal-neutral, and teacher imports them from there. Nothing stays duplicated.

Settings stay in `web/src/portals/settings/` (`SettingsModal.tsx`, `settingsTabs.ts`, section
components). The shell opens `SettingsModal`; each portal passes its tab list.

### Portal content

Student (`web/src/portals/student/shell.tsx`):

- Nav: Overview, Your classes, Standings, Friends.
- Group "Subjects": one row per enrolled subject with a grade ring; it expands to Practice,
  Flashcards, Study plan. A student with no marked paper sees "Your subjects show up here after
  your first marked paper."
- Footer: "Upload a paper" (`/student/correct`) and the user block (name, qualification and
  subject count).
- Top bar action: "Upload a paper".
- Account panel links: Profile, Parents, Recently deleted.
- Settings tabs: Profile, Account and devices, Notifications, Appearance, Install Lemely.
- Bottom tabs: today's student tabs, unchanged.

Teacher (`web/src/portals/teacher/index.tsx`): today's nav, class group, counts, Create and Upload
actions, account links and settings tabs on `develop`, passed into the same shell.

### Removed

- Student: old `Sidebar`, `Header`, `UserBlock`, `HeaderStreak` (the streak now lives in the
  Overview hero).
- Teacher: `TeacherTopBar` and the sidebar code that moves into the shell.

## 2. Behaviour

- Drawer: below 1248px the sidebar opens as a drawer from the menu button (existing
  `NavDrawer`), with focus trap and Escape to close.
- Subject tree: buttons with `aria-expanded`; the current route's subject starts expanded.
- Notifications panel: uses the existing notification count and list queries per portal and the
  existing mark-read mutation. Titles wrap to two lines (as on `develop`).
- Account panel: Sign out uses the existing sign-out that awaits cache clearing.
- Settings dialog: `/<portal>/settings/:tab` opens the dialog on that tab over the page the user
  came from; closing returns to that page. A fresh load of a settings URL opens it over the
  portal home. The page underneath stays mounted and scrolled; overlays do not shift layout (as
  on `develop`).
- Top bar: semi-translucent over a backdrop blur (Decision 7), so page content scrolling under
  it stays faintly visible; solid where `backdrop-filter` is unsupported. It lifts with a shadow
  once the page scrolls under it (light theme), as before.
- All motion stops under `prefers-reduced-motion`. Light and dark themes match the design.

## 3. Accessibility

Skip link to main content; one `nav` landmark for the sidebar, labelled; panels are
keyboard-reachable with visible focus and return focus to their trigger on close; touch targets
at least 44px on coarse pointers; 375px top bar keeps a readable title (as on `develop`).

## 4. Testing and drift gate

### Drift gate

- Script: the Overview spec's `web/scripts/home-drift.mjs`, extended with shell scenes.
- Student shell vs design A: Overview, a Subject page and Notifications × the 390, 768, 1024,
  1440 and 1920 windows × light and dark. Interaction scenes: drawer open, bell panel open,
  account panel open, each settings tab.
- Teacher: no teacher design A preview exists. Capture teacher before (merged `develop`) and
  after at the same scenes. Every difference must be a design A shell change and is logged with
  its reason. Page content below the shell must not change.
- Pass rule: 0 differing pixels, or up to 15% with a written justification per difference that
  the user has approved (Decision 8). Teacher frame, drawer, panel and settings scenes are
  log-only. Student scenes at the 1024 window are also log-only: the app shows the drawer there
  (Decision 1), design A the sidebar.
- Behaviour check: the content under the scrolled top bar shows through faintly, in both portals
  and both themes.

### Other tests

Run only the touched test files, never the full suite.

- Vitest: settings dialog routing (open by URL, close to background entry), focus trap and
  Escape, subject tree keyboard use, panel focus return.
- Existing `navigation.test.ts` and `navShells.test.ts` for both portals keep passing; update
  only where the shell moved.
- axe on both portals' shell scenes.

## Drift log

Source: drift run `reports/.scratch/drift/2026-11-07T04-14-27-297Z` (276 keys: 42 pass, 220 fail only because approval is pending, 14 captured and not compared). Full per-key text lives in `web/scripts/drift/justifications.json`; the rows below collapse windows and themes that share a justification and give the highest % of the group. "0 px" means zero pixels differing at pixelmatch threshold 0.1 (anti-aliasing tolerance), not bit-identical files. Teacher baselines are the 144 sidecars pinned to `aa533580`.

Teacher (before = merged `develop`, after = this branch). Every row is log-only (no 15% cap) and needs approval.

| Scene | Difference | Max % | Justification | Approved |
|---|---|---|---|---|
| Teacher content: home, class, notifications (390 to 1920, both themes; gate) | None. Page content is unchanged | 0 px (30 keys) | Content capture hides the shell and snaps the content origin, so a difference here would mean the page changed | n/a |
| Teacher frames: home, class, notifications (30 keys, log-only) | Design A shell: 216px sidebar (was 252px), drawer below 1248px (was 820px), top bar 21px/800 title, dot instead of count badge, translucent bar (86% surface, backdrop blur), page ground `surface-container`, main padding 72px (14px in drawer range) | 3.11 | Design A `.as-bar`, `.as-side`, `.as-main`; drawer breakpoint is user Decision 1; translucent bar is Decision 7 | Pending |
| Teacher drawer (390, 768; 4 keys, log-only) | Drawer is design A's `.as-side` sheet (was the old drawer) | 62.15 | Design A `.as-side`; the drawer's geometry and rows changed wholesale | Pending |
| Teacher bell (10 keys, log-only) | Panel over the page under the bar, design A `.as-pop-panel` (was a sheet on phones) | 6.74 | Design A `.as-pop-bell` | Pending |
| Teacher account (10 keys, log-only) | Panel over the page under the bar, design A `.as-pop-me` | 12.55 | Design A `.as-pop-me` | Pending |
| Teacher settings: profile, account, notifications, appearance, classes, install (60 keys, log-only) | Settings open as a dialog over the page (was a page); the 390px keys pass at 0 px | 62.41 | Spec section Settings dialog; design A `.as-settings` | Pending |

Student (before = design A preview kit, after = the app).

| Scene | Difference | Max % | Justification | Approved |
|---|---|---|---|---|
| Student frames: populated, new, subject, notifications (32 keys at 390, 768, 1440, 1920; gate) | Tutors and Sessions rows after Friends, so Subjects sits 74px lower; Add Maths closed and untinted until the Overview plan passes `fallbackId`; kit squircle avatar (not design A's circle); `BottomNav` in place of design A's phone bar | 1.51 | Decisions 2, 4, 5 and the temporary Add Maths deferral | Pending |
| Student bell and account (16 keys at 390, 768, 1440, 1920; gate) | Same sidebar and avatar differences as the frames; bell and account panels as in design A | 1.75 | Decisions 2 and 4 | Pending |
| Student drawer, on the subject route (390, 768; 4 keys; gate) | Tutors and Sessions rows; closed untinted Add Maths | 9.14 | Decision 2; Add Maths deferral | Pending |
| Student drawer, on `/student` (390, 768; 4 keys, log-only) | As above, with the closed Add Maths group moving the phone sheet's top | 17.21 | Add Maths deferral (temporary, P2 Task 13/18) | Pending |
| Student settings: profile, account, notifications, appearance, install (40 keys at 390, 768, 1440, 1920; gate) | Dialog chrome and section bodies differ from design A (for example Appearance uses radios, design A a segmented control) | 10.33 | Shared `portals/settings` sections reused; see the open restyle decision below | Pending |
| Student at 1024px: every scene above (22 keys, log-only) | Sidebar hidden; menu button and drawer instead of design A's sidebar | 5.40 | Drawer below 1248px; user Decision 1 | Pending |
| Student, phone widths | Today's `BottomNav` (5 tabs, below 820px) in place of design A's own 4-item phone bar (720px and below); between 721 and 819px the menu button and the tab bar both show; no bar at 768px in design A | 1.44 at 390, 0.33 at 768 (populated frame) | Phone navigation parity with teacher; user decision 2026-11-06 (Decision 5) | Yes |

### Not captured

- Hover colours: design A's `--surface-hover-tint` is mapped to `surface-container`; hover states are not in any scene.
- The pre-mount shell: `index.html` still paints the 252px / 820px sidebar before React mounts (see Risks 9).
- The bar's blur radius: 10px `--blur-nav` against the preview's 14px. Nothing sits under the bar at scroll 0, so no scene can see it.
- Teacher natural-height content (12 keys) and the teacher drawer at 1100px (2 keys) are captured and not compared; they need human eyes.
