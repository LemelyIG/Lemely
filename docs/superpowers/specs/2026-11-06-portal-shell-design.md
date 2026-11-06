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
| `ShellTopBar.tsx` | Floating bar: menu button, page title, primary action, bell, gear, avatar; breadcrumbs only when drilled in. | `TeacherTopBar` |
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
- Pass rule: 0 differing pixels, or up to 15% with a written justification per difference.

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
| Student, phone widths | Bottom tab bar present; design has none | (measure) | Phone navigation parity with teacher; user decision 2026-11-06 | Yes |
