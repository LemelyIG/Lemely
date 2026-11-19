# Redesign Implementation: Master Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship every approved redesign screen, and the backend those screens need, into `develop`. Do it in parallel lanes, with no live feature lost.

**Architecture:** A UI kit foundation (F1) comes first. Then 12 vertical-slice lanes run in three waves of four. Each lane has its own plan file, its own worktree and branch (`redesign/<lane>`, cut from `develop` after F1 lands), and its own PR to `develop`. This master plan owns the cross-lane rules: file ownership, the F1 interface contract, merge order, and gates.

**Tech Stack:**
- Web: React 19, react-router 7, TanStack Query, Tailwind 4, Radix, Vitest, Playwright, phosphor icons
- Backend: FastAPI with routers in `lemely/web/routers/` and schemas in `lemely/web/schemas_<area>.py`
- Database: SQLAlchemy and Alembic

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md`

## Global Constraints

Every lane plan inherits these:
- Signed commits only, with explicit paths: `git commit -S -- <paths>`. Run `pre-commit run --files <touched files>` (with `PYTHONPATH=<worktree>`) before every commit.
- Never run the full test suite locally. Run only the touched test files; CI runs the rest. Lint tests that scan source (`tests/test_*lint*`, `check:copy`, `check:native`) count as touched whenever you touch the source they scan.
- Never push to `main`, and never open a PR against it. PRs target `develop`.
- No token or Abyss v5 changes. Use the existing design tokens.
- Any Alembic migration must have a downgrade. Stop and ask the user before running a migration against any shared database. Writing the migration file and testing it on a throwaway test database is allowed.
- Shell rule: the merged `PortalShell` (top bar, sidebar, native tab bar, sheets, pull-to-refresh) wins. Page content follows the mock exactly.
- Fidelity: every mock frame becomes a real state at 390px, tablet and 1280px. Every mock animation is built and honours `prefers-reduced-motion`. Each lane ends with one side-by-side screenshot per screen (mock against app, 390 and 1280), a drift fix, and an `/impeccable polish` pass. There is no pixel-diff gate.
- Changes from the mock: list small fixes in the PR (spacing, accessibility, contrast, motion, typos, edge cases). Layout, flow or content changes need user approval first.
- Taste: read `~/.claude/projects/-home-sico-Code-Lemely/memory/design-taste-first-try.md`, `design-redesign-decisions.md` and `design-empty-sparse-states.md` before UI work.
- Binny appears at most once per screen. Student screens get the full Binny, teacher screens a small head-crop Binny in calm moments only, and parent screens no Binny.
- Use Mono for numbers. Use gold only for earned things. Keep copy short: Binny lines are 2–4 words, with no eyebrow or kicker labels.
- Model cost stays well under $0.10 per paper, and each model call reports its cost.
- Every new route uses the existing auth and tenancy dependencies (`lemely/web/deps.py`). Parent access goes through the parent link. Students and parents can only read crops of papers they own or are linked to.

## Lanes and plan files

| Id | Lane | Plan file | Wave |
|---|---|---|---|
| F1 | UI kit and shell additions | `2026-11-15-redesign-f1-ui-kit.md` | 0 |
| F2 | Groundwork: mocks merged, widget clock fix | done on branch `redesign/f2-groundwork` | 0 |
| L1 | Student Home hub and Me | `2026-11-15-redesign-l01-home-me.md` | 1 |
| L2 | Subject | `2026-11-15-redesign-l02-subject.md` | 1 |
| L3 | Practice run, start and result | `2026-11-15-redesign-l03-practice-run.md` | 1 |
| L4 | Practice tab and set builder | `2026-11-15-redesign-l04-practice-tab.md` | 1 |
| L5 | Teacher review queue | `2026-11-15-redesign-l05-review-queue.md` | 2 |
| L6 | Upload, camera, processing | `2026-11-15-redesign-l06-upload.md` | 2 |
| L7 | Student paper result S1 | `2026-11-15-redesign-l07-result-s1.md` | 2 |
| L8 | Teacher papers, heatmap, StudentDetail | `2026-11-15-redesign-l08-teacher-papers.md` | 2 |
| L9 | Study plan | `2026-11-15-redesign-l09-study-plan.md` | 3 |
| L10 | Flashcards | `2026-11-15-redesign-l10-flashcards.md` | 3 |
| L11 | Parent subject, topics, Emails | `2026-11-15-redesign-l11-parent.md` | 3 |
| L12 | Pipeline: blank flag, cover names | `2026-11-15-redesign-l12-pipeline.md` | 3 |

F2 shrank to the mocks merge and a CI fix. Lanes do not need pre-made hook-up points, because the codebase already uses one router file, one `schemas_<area>.py` and one `lib/<area>Types.ts` per area. Lanes add their own files and append one registration line to each shared file (see Shared files).

A lane may start before its wave when its owned files don't overlap any open lane's files. Lanes L9, L10 and L11 don't overlap W1 or W2, so they start as soon as a slot frees up.

## F1 interface contract

All lanes code against these names. F1 builds them; lane plans import them. Every name below is exported from `web/src/components/redesign/index.ts`. Any extra optional prop F1 adds must keep these signatures.

```ts
export type BinnyMood = 'happy' | 'wink' | 'open' | 'thinking' | 'sad';
export type BinnyMotion = 'idle' | 'hop' | 'roam' | 'pop' | 'none';
// Official geometry from portals/marketing/Binny.tsx. Under prefers-reduced-motion every motion becomes 'none'.
export function Binny(p: { mood: BinnyMood; size?: number; motion?: BinnyMotion; className?: string; 'aria-hidden'?: boolean }): JSX.Element;
// Binny plus a short speech bubble (2–4 words). One per screen.
export function BinnyLine(p: { mood: BinnyMood; line: string; motion?: BinnyMotion; size?: number }): JSX.Element;

export type Grade = string; // 'A*' | 'A' | ... | 'G' | 'U'
// The Steps grade path: one solid bar per paper, a solid goal block, letters on one baseline.
export function StepsPath(p: { papers: { id: string; label: string; grade: Grade; pct: number }[]; goal?: Grade; onSelect?: (id: string) => void }): JSX.Element;

// The gold three-part ring. Values run 0..1. Gold only when a part is complete.
export function GoldRing(p: { parts: [number, number, number]; size?: number; label?: string; center?: React.ReactNode }): JSX.Element;
// The single big key-number ring, such as confidence or level.
export function KeyRing(p: { value: number; size?: number; tone?: 'tide' | 'gold' | 'ok' | 'warn'; center: React.ReactNode; label: string }): JSX.Element;

export type TileTone = 'tide' | 'sea' | 'gold' | 'coral' | 'violet' | 'mint';
// A tinted tile with a big faint icon (Practice tab C).
export function Tile(p: { icon: React.ElementType; title: string; status?: string; tone: TileTone; big?: boolean; to?: string; onClick?: () => void; disabled?: boolean }): JSX.Element;

export function H2Row(p: { title: string; link?: { label: string; to?: string; onClick?: () => void } }): JSX.Element;
export function HairRows(p: { children: React.ReactNode; 'aria-label'?: string }): JSX.Element; // a <ul> of hairline rows
export function HairRow(p: { leading?: React.ReactNode; title: React.ReactNode; sub?: React.ReactNode; trailing?: React.ReactNode; to?: string; onClick?: () => void; selected?: boolean }): JSX.Element;

export type TopicState = 'work' | 'getting' | 'secure'; // labelled "Work on", "Getting there", "Secure", each with its icon
export function TopicChip(p: { topic: string; state: TopicState; onClick?: () => void }): JSX.Element;
export function TopicChips(p: { topics: { topic: string; state: TopicState }[]; foldSecure?: boolean; onSelect?: (topic: string) => void }): JSX.Element;

export type Trend = 'better' | 'worse' | 'same';
// The parent ranked row: rank, title, subject, marks lost, trend, optional "Assigned" tag, optional marks-lost bar.
export function RankRow(p: { rank: number; title: string; sub?: string; marksLost: number; trend: Trend; assigned?: boolean; bar?: number /*0..1*/; selected?: boolean; onClick?: () => void }): JSX.Element;

// The first-run walkthrough list, with numbered tips.
export function Walkthrough(p: { steps: { icon: React.ElementType; title: string; body?: string }[] }): JSX.Element;
// Ghost skeleton rows that match the hairline-row geometry.
export function GhostRows(p: { rows?: number; withLeading?: boolean }): JSX.Element;

export function ComboChip(p: { count: number }): JSX.Element; // hidden below 2, bumps when count rises
export function LevelBar(p: { level: number; xp: number; nextXp: number }): JSX.Element;
// Neutral pill. Inside 30 days of the exam it turns Tide (tone 'near'). `now` is injectable for tests.
export function CountdownPill(p: { examDate: string; now?: Date }): JSX.Element;
export function countdownTone(examDate: string, now?: Date): 'neutral' | 'near';
```

Reuse the existing kit for anything not listed: `components/ui/stepper.tsx`, `switch.tsx`, `bottom-sheet.tsx`/`sheet.tsx`, `chip.tsx`, `skeleton.tsx`, `state-views.tsx`, `query-state.tsx`, `confirm-modal.tsx`, `toast.tsx`, `progress-ring.tsx`. F1 restyles these to match the mocks where they differ, without breaking any current caller.

F1 also adds these to the shell:
- **Student nav:** Scan in the centre of the student native tab bar, and "Scan a paper" in the desktop rail, both going to the existing scan or upload route.
- **Parent shell:** a child switcher (`ChildSwitcher`, exported from `web/src/portals/parent/ChildSwitcher.tsx`) and four tabs: Overview, Topics, Inbox, Tutoring. The Topics tab points at `/parent/:childId/topics`. Until L11 lands, that route shows the existing `Weaknesses` screen. On desktop the child switcher sits in the rail.

## Shared files

Lanes may only edit these with the narrow edits listed. Conflicts are resolved by rebasing on `develop` before merge.

| File | Allowed lane edit |
|---|---|
| `lemely/web/app.py` | add one `include_router` line plus its import |
| `web/src/routes.tsx` | add or replace the route entries for the lane's own screens |
| `web/src/lib/api.ts` | add the lane's functions in one contiguous block headed by a `// <lane id>` comment, or put them in a new `web/src/lib/<area>Api.ts` |
| `web/src/lib/hooks/*` query keys | add the lane's own keys only |
| `lemely/db/models/*` | only L1, L6, L9, L11 and L12, and only where their plan names it |
| `alembic/versions/*` | new file per lane. Before merge, rebase its `down_revision` onto the `develop` head |

Owned directories:
- L1: `portals/student/screens/Overview.tsx`, `Profile.tsx` and `portals/student/home/`
- L2: `Subject.tsx`
- L3: `practice/PracticeSet.tsx` and `practice/PracticeResult.tsx`
- L4: a new `practice/PracticeHub.tsx` and the set builder, which replaces `practice/PracticeGenerator.tsx`. L4 owns `practiceData.ts` and L3 coordinates edits through it.
- L5: `teacher/screens/Review.tsx`, `ReviewItem.tsx` and a new `teacher/screens/review/` directory
- L6: the upload, camera and processing files, `CorrectPaper.tsx` and `components/CameraCapture.tsx`
- L7: `PaperResult.tsx`
- L8: `ClassPapers.tsx`, `Grading.tsx` and `StudentDetail.tsx`. L8 imports L5's paper view, from `teacher/screens/review/`.
- L9: `studyplan/*`
- L10: `flashcards/*`
- L11: `parent/screens/SubjectDetail.tsx`, `Weaknesses.tsx` and a new `parent/screens/Emails.tsx`
- L12: the marking pipeline (`lemely/io/correction_ai.py` and related), cover-name reading, and the teacher fix-it list. L12 wires these into L6's files after L6 merges.

## Merge order and dependencies

1. F2 (`redesign/f2-groundwork`): PR into `develop`, merged once CI is green.
2. F1: cut from `develop` after F2 merges, or rebased onto it.
3. W1 (L1–L4) cut from `develop` after F1 merges. L9, L10 and L11 may start in any free slot.
4. W2: L5 lands before L8's paper-view task. L8 does its other tasks first.
5. W3: L12 starts after L6 merges.

## Per-lane workflow

Each lane follows its plan file through subagent-driven development:
1. Implementer subagent per task: `implementer` for backend, `designer` for UI. The designer invokes the impeccable skill and reads `.claude/skills/impeccable/reference/craft-floor.md` before UI edits.
2. A spec-compliance review, then a code-quality review, after each task.
3. At lane end:
   - side-by-side fidelity screenshots and an `/impeccable polish` pass
   - the keep-list check: every live feature is ticked off in the PR body
   - push, then a PR to `develop`
   - an Opus review, the fixes, a green CI run, and the merge

## Self-check

- [ ] Every spec group maps to a lane: Home+Me L1, Subject L2, practice run L3, Practice tab L4, review queue L5, upload L6, S1 L7, teacher papers L8, study plan L9, flashcards L10, parent L11, pipeline L12, and empty or sparse states inside every lane.
- [ ] The F1 contract is the single source of truth for shared names.
