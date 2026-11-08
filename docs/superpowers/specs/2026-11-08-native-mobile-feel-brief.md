# Native mobile feel: design brief

Status: confirmed via `/impeccable shape`, 2026-11-08. No code yet.

## 1. Job and audience

- **Who:** students on phones (mostly Android in Egypt, some iPhone), parents (mobile-first, later), teachers who check something on the go. Often installed to the home screen as a PWA, so there is no browser chrome to lean on.
- **Mode:** Operate (dashboards, correction, settings) and Read (marked papers, flashcards). Not the landing page, which stays Persuade and is out of scope.
- **Need:** Lemely should feel like an app they installed, not a website shrunk to fit. Chrome stays put, gestures work, overlays come from where the thumb is, and lists look like the phone's own lists.

## 2. Outcome and proof

- On a phone, a student cannot easily tell Lemely from a native app in the first minute: pinned header, tab bar, sheets, swipe-back, pull-to-refresh, press feedback.
- On iPhone it reads as iOS, and on Android it reads as Material 3. The brand stays Lemely on both: Abyss/Tide, Clip Letters, Bricolage/Schibsted/JetBrains Mono, and no SF Pro.
- **Proof:** screenshots at 390×844 (iOS UA) and 412×915 (Android UA), light and dark, at rest and scrolled, for each tab root and one detail page per portal. Also a short screen recording of the collapse, sheet drag, swipe-back and pull-to-refresh.

## 3. Selected direction

**Thesis: "The page is the app's own list; the chrome is glass."** Desktop keeps design A: floating bar, sidebar, cards. Below the phone breakpoint (`shell-sm`, 720px) the shell switches to a native frame:

1. **Large-title header that collapses (the user's choice).**
   - At the top of a tab root, the bar row holds only the actions (bell, settings, avatar, primary action icon). The page title sits below at large-title size: Bricolage 800, 34px, which is allowed because it is at least 28px.
   - On scroll, the large title scrolls away and a compact inline title fades into the pinned bar. Inline title: 17px Schibsted 600, centred on iOS and start-aligned on Android.
   - **iOS bar:** goes from transparent to a blurred translucent surface (`.lm-shell-bar-glass` family) with a 0.5px `outline-variant` hairline that only appears once content is underneath.
   - **Android bar:** goes from `surface` to `surface-container` (M3 lift-on-scroll), with no shadow and no hairline.
   - Detail pages skip the large title. They use the compact bar with a back chevron and title from the start.
   - The bar sits under the status bar using `env(safe-area-inset-top)`. In standalone mode on iOS the status-bar style becomes `black-translucent`, so the glass runs under the clock.
2. **Tab bar (exists; refine).**
   - **iOS:** about 49px plus the home-indicator inset, translucent glass, 10–11px labels, icons outline at rest and filled when selected (Phosphor `regular` and `fill` weights), tinted in `primary`.
   - **Android:** 80dp, with an M3 active-indicator pill (64×32, `secondary-container`) behind the selected icon.
   - The raised "Correct" button stays as Lemely's one signature moment.
   - Tapping the active tab scrolls to top. Tapping it again pops to the tab root.
3. **Sheets, not dialogs or popovers.**
   - Below `shell-sm`, `Modal`, `ConfirmModal`, the settings dialog, the bell panel, the avatar panel, filters and selects all open as bottom sheets.
   - Sheet anatomy: grabber (36×5 on iOS, 32×4 on Android), top radius `--radius-card` (24px), and a scrim.
   - Gestures: drag to dismiss, and two detents (medium and large) where the content is long. On iOS, the page behind scales back slightly at the large detent.
   - Back and Escape close the sheet (`useDialogHistory` already exists).
   - Destructive confirms use an action sheet on iOS (stacked rows, Cancel separated) and an M3 dialog-style sheet on Android.
4. **Edge-to-edge grouped content.**
   - Below `shell-sm`, page cards drop their floating, inset, outlined look. Sections become full-bleed groups: a section header in the label style, and rows on `surface-container-lowest` against a `surface-container-low` page.
   - **iOS:** inset-grouped sections with a 10–12px radius and 16px margins, 44px minimum rows, and separators inset from the leading edge.
   - **Android:** full-width list items (56/72/88 for one, two and three lines) with 16px padding and no separators inside a group.
   - Data-heavy blocks (charts, mark tables, the grade ladder) stay as one full-width group, not cards on cards.
5. **Touch feedback everywhere.**
   - Every tappable element gets a press state. iOS: a background dim of about 8% plus scale 0.97 on buttons. Android: an M3 state layer (pressed 10%) with a ripple from the touch point.
   - No hover-only affordances below `shell-sm`.
   - 44px minimum targets, which the existing `pointer-coarse:` sizing becomes the rule for.
   - Android-only haptics: `navigator.vibrate(10)` on commit gestures (pull-to-refresh trigger, sheet snap, long-press).
6. **Gestures and motion.**
   - Edge swipe-back extends from standalone-only to all phone sessions where the browser has no own back gesture. Where it does (iOS Safari tab, Android system back), defer to the system.
   - Interactive swipe: the page follows the finger with about 30% parallax underneath, then commits or cancels.
   - Pull-to-refresh spreads from 3 student screens to every list or overview root in both portals, with `overscroll-behavior-y: contain` on the scroller.
   - Tab switches crossfade. Pushes slide in (the existing `data-direction` view transitions), using M3 emphasized easing on Android and an iOS-like spring curve on iPhone.
   - `prefers-reduced-motion` turns all of it off.
7. **Platform switch.**
   - One boot-time resolver sets `html[data-platform="ios|android|other"]`, using `navigator.userAgentData.platform` with a UA fallback. iPadOS counts as iOS.
   - Styles key off it with Tailwind custom variants (`ios:` and `android:`). Desktop and `other` keep design A.
   - There are no separate component trees. The same component varies by tokens and small markup flags only.

## 4. Scope and boundaries

- **In scope:** the shell for every portal (student, teacher, and later parent and admin through the same `PortalShell`), the `Modal`, `ConfirmModal`, popover, select, panel and sheet primitives, card and section primitives at phone width, gestures, PWA meta, and every screen's phone layout as far as it inherits from those primitives.
- **Fidelity:** production, built in the real app, plus design A's preview kit (`student-home-a.html`) updated first so the drift gate has a reference. See the open decisions.
- **Untouched:**
  - Desktop and tablet (≥721px) layouts.
  - The brand tokens, typefaces, Jewel grades and Binny rules.
  - The landing page.
  - The approved shell drift baselines for desktop.
- **Anti-goals:**
  - A fake iOS skin: SF Pro, an iOS-blue accent, or system grey everywhere.
  - Material You dynamic colour.
  - Emoji or confetti.
  - Bottom sheets on desktop.
  - Gestures that break text selection on content.
  - Copying a specific app's look.

## 5. States and ranges

- **Header:** titles from "Overview" up to long subject and paper names like "0625 Physics · Paper 4 · May/June 2024". These truncate with an ellipsis in the inline bar and wrap to 2 lines as a large title.
- **Badges:** the bell badge runs 1 to 99+, and the Review count on the teacher tab can be large.
- **Sheets:** from one-line confirms to the full settings content, which needs the large detent with an inner scroll. Sheets must cope with the keyboard: on iOS, position by `visualViewport`, because `interactive-widget` is ignored there.
- **Lists:** empty, loading (skeleton rows in the group shape), error, and up to hundreds of rows (teacher grading).
- **Offline, queued-upload and update-toast banners:** these stack between the bar and content, or above the tab bar, without covering either.
- **Standalone vs browser tab:**
  - Standalone gets swipe-back and the status-bar glass.
  - In an iOS Safari tab, the system swipe and Safari's toolbar take precedence.

## 6. Interaction and layout

- **Hierarchy on a phone tab root:** status bar, glass bar (actions), large title, content groups, tab bar.
- **Detail page:** status bar, compact bar (back, title, one action), content, tab bar. Full-screen flows such as camera, the correction run, and a paper review hide the tab bar.
- **Collapse mechanics:** CSS scroll-driven animation (`animation-timeline: scroll()`) where supported, with a passive scroll listener plus rAF fallback for older iOS. One threshold: the large title's bottom crossing the bar.
- **Sheets:** a modal `<dialog>` or the existing portal `Modal`, restyled through one `useIsPhone()` / `shell-sm` switch, keeping the existing a11y contract (focus trap, return focus, labelled).
- **Feedback:** press visible in under 50ms, sheet snap within 250–350ms, and swipe commit at 35% width or a fast fling.

## 7. Constraints and open decisions

**Constraints:**
- React 19, Vite, Tailwind v4, and a PWA.
- iOS Safari has no Vibration API and no `interactive-widget`. Scroll timelines need iOS 26 or later.
- WCAG AA, plus the RTL-safe logical properties already required. The swipe-back direction mirrors in RTL, and `edgeSwipeBack` already tracks direction.
- Reuse what exists: `Sheet` (adaptive), `useDragGesture`, `usePullToRefresh` with `PullIndicator`, `useLongPress`, `EdgeSwipeBack`, `useDialogHistory`, `ScreenOutlet` and `data-direction` transitions, `pointer-coarse:` sizing, and `.lm-shell-bar-glass`.

**Decisions (user confirmed, 2026-11-08):**
1. **Drift rule: update the preview first.** Redesign the phone frame in `student-home-a.html`, then port it to the app under the existing drift gate.
2. **Sequencing: native frame first.** Build the frame and primitives before P2 (the new student overview), so P2's phone layout is born edge-to-edge.
3. **Typeface: brand fonts everywhere.** iOS gets no system font in the chrome.
4. **Teachers: same native frame.** Dense grading tables become list rows on phones, with a "view table" escape hatch.
5. **DESIGN.md.** Replace "drawer for teachers" with the native-frame rules when the frame lands.

## Research sources

Apple HIG, via third-party measurements because the HIG pages are JS-rendered; verify the numbers in the iOS Figma kit before they become tokens. Material Components docs (navigation bar, top app bar, bottom sheet). web.dev "App design". Chrome viewport-resize and View Transitions guides. WebKit's Safari 26 notes on scroll-driven animations. MDN on Popover, Vibration and `userAgentData`. Konsta UI as a Tailwind reference for iOS vs Material dimensions.
