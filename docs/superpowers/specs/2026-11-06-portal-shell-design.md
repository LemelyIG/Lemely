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

| Scene | Difference | % pixels | Justification | Approved |
|---|---|---|---|---|
| Student, phone widths | Today's bottom tab bar instead of the design's own 4-item phone bar (≤720px) | (measure) | Phone navigation parity with teacher; user decision 2026-11-06 | Yes |
| Student, 1024px (all scenes, log-only) | Sidebar hidden; menu button and drawer | (measure) | Drawer below 1248px; user decision 2026-11-06 (Decision 1) | Pending |
| Teacher frames (log-only) | Top bar semi-translucent (86% surface, backdrop blur) | (measure) | Design A `.as-bar` `@supports` rule; user decision 2026-11-06 (Decision 7) | Pending |
