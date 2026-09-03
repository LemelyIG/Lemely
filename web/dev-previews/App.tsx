import { useState, type CSSProperties } from "react"
import { MagnifyingGlass, Plus } from "@phosphor-icons/react"
import { ComponentSection, Group, StateCell, slug } from "./harness"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { FileDrop } from "@/components/ui/file-drop"
import { Select } from "@/components/ui/select"
import { RadioGroup, Radio } from "@/components/ui/radio"
import { Switch } from "@/components/ui/switch"
import { Checkbox } from "@/components/ui/checkbox"
import { Badge } from "@/components/ui/badge"
import { SubjectTag } from "@/components/ui/subject-tag"
import { Avatar } from "@/components/ui/avatar"
import { Kbd } from "@/components/ui/kbd"
import { ProgressBar } from "@/components/ui/progress-bar"
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/table"
import { Tabs, TabsList, TabsPanel } from "@/components/ui/tabs"
import { SkeletonLine, SkeletonBlock, SkeletonCircle, SkeletonText } from "@/components/ui/skeleton"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { Modal } from "@/components/ui/modal"
import { Popover } from "@/components/ui/popover"
import { ToastCard, ToastProvider, useToast } from "@/components/ui/toast"
import { EmptyState, ErrorState, RouteFallback } from "@/components/ui/state-views"
import { QueryState, type QueryStateQuery } from "@/components/ui/query-state"
import { ApiError } from "@/lib/api"
import { ChartFrame } from "@/components/ui/chart-frame"
import { Breadcrumbs } from "@/components/ui/breadcrumbs"
import { NavDrawerTrigger } from "@/components/ui/nav-drawer"
import { SkipLink } from "@/components/ui/skip-link"
import { GettingStarted } from "@/components/ui/getting-started"
import { FullPageState } from "@/portals/misc/FullPageState"
import { OfflineBannerView } from "@/components/ui/offline-banner"
import { RECONNECTED_TOAST, UPDATED_TOAST } from "@/components/recovery-effects"

/**
 * The component-kit preview page (REDESIGN-MISSION §5 Phase 2.6).
 *
 * Two jobs, in this order of importance:
 *
 * 1. **Prove the eight states exist.** A component that has never been rendered
 *    disabled, or in error, or loading, does not have those states, it has an
 *    intention to have them. Every interactive component in the kit appears
 *    here with each state rendered and labelled by how it was produced (see
 *    `harness.tsx`).
 * 2. **Be the reference for the tokens themselves**, so a later phase can check
 *    a colour or a type rung by looking rather than by reading `index.css`.
 *
 * This page is not a product surface and is not reachable from the app. Run it
 * with `npm run preview:kit`.
 */

/*
 * Every Tailwind class below is written out in full, never assembled from a
 * template literal. Tailwind v4 finds classes by scanning source text for
 * literal strings, so `bg-pastel-${name}` generates no CSS at all and the
 * swatch silently renders unstyled. That is easy to miss on a page whose whole
 * job is to show colours, which is exactly why it is spelled out here.
 */
const PASTELS = [
  ["rose", "Unassigned or other subjects", "bg-pastel-rose", "text-pastel-rose-ink"],
  ["amber", "English", "bg-pastel-amber", "text-pastel-amber-ink"],
  ["sage", "Chemistry", "bg-pastel-sage", "text-pastel-sage-ink"],
  ["sky", "Mathematics", "bg-pastel-sky", "text-pastel-sky-ink"],
  ["lilac", "Physics", "bg-pastel-lilac", "text-pastel-lilac-ink"],
  ["clay", "Biology", "bg-pastel-clay", "text-pastel-clay-ink"],
] as const

const SEMANTIC = [
  ["ok", "Correct, complete, saved, on track", "bg-ok-wash", "text-ok"],
  ["warn", "Partial credit, uncertain, borderline", "bg-warn-wash", "text-warn"],
  ["err", "Wrong, failed, destructive, blocked", "bg-err-wash", "text-err"],
  ["info", "Neutral notices and tips", "bg-info-wash", "text-info"],
] as const

const SURFACES = [
  ["paper-raised", "bg-paper-raised"],
  ["paper", "bg-paper"],
  ["paper-sunk", "bg-paper-sunk"],
] as const

const TYPE_RUNGS = [
  ["text-display-hero", "Display hero, marketing only"],
  ["text-display-xl", "Display xl"],
  ["text-display-lg", "Display lg, in-app page titles"],
  ["text-display-md", "Display md, section headings"],
  ["text-display-sm", "Display sm, sub-sections"],
  ["text-body-lg", "Body lg, the default"],
  ["text-body-md", "Body md, dense"],
  ["text-body-sm", "Body sm, captions"],
  ["text-label", "Label, buttons and form labels"],
  ["text-eyebrow", "Eyebrow, uppercase kicker"],
  ["text-data-lg", "Data lg, the big number"],
  ["text-data-md", "Data md, inline figures"],
  ["text-data-sm", "Data sm, codes and metadata"],
  ["text-hand", "Marginalia, decorative only"],
] as const

/** What to do to see the states a static render cannot show. */
const INTERACT_NOTE: Record<string, string> = {
  hover: "Hover this control to see it",
  "focus-visible": "Press Tab to move focus onto this control",
  active: "Press and hold this control to see it",
}

const SECTIONS = ["Colour", "Typography", "Texture", "Forms", "Display", "Overlays"] as const

/**
 * A stand-in for a chosen scan, so `FileDrop`'s success state can be shown
 * without a real picker interaction. Its byte content is irrelevant — the
 * component reads only `name` and `size` — but it is a genuine `File`, not a
 * shape cast to one, so the preview exercises the same code path the screen
 * does.
 */
const PREVIEW_FILE = new File(
  [new Uint8Array(1_487_232)],
  "0625_w24_qp_41.pdf",
  { type: "application/pdf" },
)

/**
 * The eight-state grid for one component.
 *
 * `render` receives the state and returns the component in it. Hover and
 * active come back wrapped in `Force`, which pins the pseudo-class so the
 * state is visible in a static screenshot; every other state is real.
 */
function StateGrid({
  render,
  notes = {},
}: {
  render: (state: string) => React.ReactNode
  notes?: Record<string, string>
}) {
  return (
    <>
      {["default", "hover", "focus-visible", "active", "disabled", "loading", "error", "success"].map(
        (s) => {
          const interactive = s === "hover" || s === "active" || s === "focus-visible"
          const provenance = interactive ? "live" : "prop"
          const body = render(s)
          return (
            <StateCell
              key={s}
              state={s as never}
              provenance={provenance as never}
              note={notes[s] ?? INTERACT_NOTE[s]}
            >
              {body}
            </StateCell>
          )
        },
      )}
    </>
  )
}

/** Toast needs to be triggered, so it lives behind a button inside the provider. */
/**
 * Pin `RouteFallback` to one loading tier. Its two tiers are staged purely by
 * the `--loading-tier-*` tokens (the delays on `.lm-tier-skeleton` and
 * `.lm-tier-slow` in index.css), so a wrapper that overrides those tokens
 * shows a tier at once (`0s`) or holds it off for the life of the page
 * (`9999s`) without the component needing a preview-only prop. `HELD` is
 * not `infinite`: an animation-delay has no such keyword.
 */
const HELD = "9999s"
function tierStyle(skeleton: string, slow: string): CSSProperties {
  return { "--loading-tier-skeleton": skeleton, "--loading-tier-slow": slow } as CSSProperties
}

function ToastDemo() {
  const { toast } = useToast()
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" onClick={() => toast({ title: "Paper marked", variant: "success" })}>
        Success
      </Button>
      <Button
        size="sm"
        onClick={() => toast({ title: "We couldn't upload that file", variant: "error" })}
      >
        Error
      </Button>
    </div>
  )
}

/**
 * `Tabs` and `RadioGroup` are controlled-only by design (their own comments
 * explain why: every real usage needs to read or drive the value from
 * outside). The preview therefore has to own the state rather than lean on a
 * `defaultValue` convenience prop, which is the honest way to demo them: if
 * the preview needed an uncontrolled escape hatch that real screens do not
 * get, the preview would be lying about the component.
 */
function TabsDemo() {
  const [tab, setTab] = useState("marks")
  return (
    <div className="w-full">
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList
          label="Result sections"
          tabs={[
            { value: "marks", label: "Marks" },
            { value: "notes", label: "Notes" },
            { value: "gone", label: "Disabled", disabled: true },
          ]}
        />
        <TabsPanel value="marks">
          <p className="text-body-md text-ink-muted">Sixty three out of eighty.</p>
        </TabsPanel>
        <TabsPanel value="notes">
          <p className="text-body-md text-ink-muted">Two marks on the gradient.</p>
        </TabsPanel>
      </Tabs>
    </div>
  )
}

function RadioDemo({
  name,
  state,
  error,
}: {
  name: string
  state?: "success" | "loading"
  error?: string
}) {
  const [value, setValue] = useState("41")
  return (
    <RadioGroup
      label="Paper variant"
      name={name}
      value={value}
      onValueChange={setValue}
      state={state}
      error={error}
    >
      <Radio value="41" label="Paper 41" />
      <Radio value="42" label="Paper 42" />
      <Radio value="43" label="Paper 43" />
    </RadioGroup>
  )
}

function ModalDemo() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Open modal
      </Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Delete this paper?">
        <p className="text-body-md text-ink-muted">
          The marks and the annotations go with it. This cannot be undone.
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={() => setOpen(false)}>
            Delete
          </Button>
        </div>
      </Modal>
    </>
  )
}

/**
 * `QueryState`'s demo payload: one row list, small enough to read in a
 * 260px-wide cell. `data.rows` is what `isEmpty`/`empty` and the loaded
 * render below both key off, the same as a real screen's DTO would be.
 */
interface QueryStateDemoData {
  rows: { id: string; label: string }[]
}

/** The loaded render every `QueryState` demo cell shares, so the cells below
 * differ only in `query`, which is the thing being demonstrated. */
function QueryStateDemoPanel({ rows }: { rows: QueryStateDemoData["rows"] }) {
  return (
    <ul className="flex w-full flex-col gap-1.5">
      {rows.map((row) => (
        <li key={row.id} className="text-body-sm text-ink">
          {row.label}
        </li>
      ))}
    </ul>
  )
}

/**
 * Five hand-built `QueryStateQuery` objects, one per cell below. Hand-built
 * rather than a real `useQuery()` call because a live query cannot be forced
 * into "pending forever", "pending and idle" or "failed with a 503" on
 * demand for a static preview page, and `QueryState`'s whole point is that a
 * hand-built object satisfies the same structural type a real query result
 * does, with no cast.
 */
const QUERY_STATE_DEMO: Record<
  "pending" | "idle" | "error" | "empty" | "success",
  QueryStateQuery<QueryStateDemoData>
> = {
  pending: { status: "pending", data: undefined, error: null, refetch: () => undefined },
  // `enabled: false`'s own resting state: `fetchStatus: "idle"` alongside
  // `status: "pending"`, which is what makes `QueryState` render `idle`
  // instead of `skeleton` — see that prop's doc comment.
  idle: {
    status: "pending",
    fetchStatus: "idle",
    data: undefined,
    error: null,
    refetch: () => undefined,
  },
  error: {
    status: "error",
    data: undefined,
    error: new ApiError(503, "503 Service Unavailable"),
    refetch: () => undefined,
  },
  empty: { status: "success", data: { rows: [] }, error: null, refetch: () => undefined },
  success: {
    status: "success",
    data: {
      rows: [
        { id: "1", label: "0625_w24_qp_41" },
        { id: "2", label: "0625_s23_qp_22" },
      ],
    },
    error: null,
    refetch: () => undefined,
  },
}

export function App() {
  return (
    <ToastProvider>
      <AppBody />
    </ToastProvider>
  )
}

function AppBody() {
  return (
    <div className="paper-grain min-h-screen">
      <header className="sticky top-0 z-[var(--z-index-nav)] border-b border-rule bg-paper/85 backdrop-blur-[10px]">
        <div className="mx-auto flex max-w-[var(--container-app)] flex-wrap items-center gap-4 px-6 py-4">
          <span className="text-display-sm text-ink">Lemely component kit</span>
          <span className="text-data-sm text-ink-faint">The Study Notebook</span>
          <nav className="ms-auto flex flex-wrap gap-3">
            {SECTIONS.map((s) => (
              <a
                key={s}
                href={`#${slug(s)}`}
                className="text-label text-ink-muted transition-colors duration-[var(--dur-instant)] hover:text-accent-ink"
              >
                {s}
              </a>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto flex max-w-[var(--container-app)] flex-col gap-section px-6 py-12">
        <p className="text-body-lg max-w-[65ch] text-ink-muted">
          Every value on this page comes from <code className="text-data-md">DESIGN.md</code> by way
          of <code className="text-data-md">src/index.css</code>. If something here looks wrong, the
          token is wrong, not the page. Contrast claims are pinned by{" "}
          <code className="text-data-md">tests/test_design_tokens.py</code>.
        </p>

        <Group title="Colour">
          <ComponentSection
            name="Paper and ink"
            summary="Cards sit lighter than the canvas, the way a sheet laid on a desk catches more light. Never pure white and never pure black: both read sterile and break the paper illusion. Ink faint is the floor, and there is deliberately no lighter text step."
          >
            <StateCell state="default" provenance="prop" note="Surfaces, lightest to darkest">
              <div className="flex w-full flex-col gap-2">
                {SURFACES.map(([name, bg]) => (
                  <div
                    key={name}
                    className={`flex items-center justify-between rounded-md border border-rule px-3 py-2 ${bg}`}
                  >
                    <span className="text-body-sm text-ink">{name}</span>
                  </div>
                ))}
              </div>
            </StateCell>
            <StateCell state="default" provenance="prop" note="Text tokens, all AA on every surface">
              <div className="flex w-full flex-col gap-1">
                <span className="text-body-lg text-ink">ink, 11.6:1</span>
                <span className="text-body-lg text-ink-muted">ink-muted, 6.09:1</span>
                <span className="text-body-lg text-ink-faint">ink-faint, 4.94:1</span>
              </div>
            </StateCell>
            <StateCell
              state="default"
              provenance="prop"
              note="Accent has three values because three jobs have three contrast requirements"
            >
              <div className="flex w-full flex-col gap-2">
                <span className="rounded-md bg-accent px-3 py-2 text-label text-accent-on">
                  accent fill, white label 4.65:1
                </span>
                <span className="text-body-md text-accent-ink">accent-ink text, 9.75:1</span>
                <span className="rounded-md bg-accent-wash px-3 py-2 text-body-sm text-accent-ink">
                  accent-wash
                </span>
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Pastels and subjects"
            summary="The sticker set. Subject colours are semantic, not decorative: a student should find Physics by colour before reading. Never pick a subject colour at a call site."
          >
            {PASTELS.map(([name, use, bg, fg]) => (
              <StateCell key={name} state="default" provenance="prop" note={use}>
                <span className={`rounded-full px-2.5 py-1 text-eyebrow ${bg} ${fg}`}>{name}</span>
              </StateCell>
            ))}
          </ComponentSection>

          <ComponentSection
            name="Semantic states"
            summary="Teal rather than green, so the success and error pair survives deuteranopia and protanopia where green against red does not. They also descend in lightness, so the ladder survives greyscale for a reader who gets no hue at all. Colour never carries meaning alone: each pairs with a label."
          >
            {SEMANTIC.map(([name, use, bg, fg]) => (
              <StateCell key={name} state="default" provenance="prop" note={use}>
                <span className={`rounded-md px-3 py-1.5 text-body-sm ${bg} ${fg}`}>{name}</span>
              </StateCell>
            ))}
          </ComponentSection>
        </Group>

        <Group title="Typography">
          <ComponentSection
            name="The four faces"
            summary="Newsreader for display, Geist for interface and body, JetBrains Mono for every number (tabular by construction, so a column of marks aligns and a counting score never jitters), and Caveat for marginalia only. If losing the text would be a problem, it is not Caveat."
          >
            {TYPE_RUNGS.map(([cls, label]) => (
              <StateCell key={cls} state="default" provenance="prop" note={cls}>
                <span className={`${cls} text-ink`}>{label}</span>
              </StateCell>
            ))}
          </ComponentSection>
        </Group>

        <Group title="Texture">
          <ComponentSection
            name="The notebook layer"
            summary="How the one protected quality survives contact with a dashboard, and the easiest thing in the system to overdo. The restraint rule: marginalia decorates, never carries meaning alone. Remove every element here and the product must still be fully usable."
          >
            <StateCell state="default" provenance="prop" note=".ruled-bg, 32px">
              <div className="ruled-bg h-24 w-full rounded-md border border-rule" />
            </StateCell>
            <StateCell state="default" provenance="prop" note=".dotted-bg, 24px">
              <div className="dotted-bg h-24 w-full rounded-md border border-rule" />
            </StateCell>
            <StateCell
              state="default"
              provenance="prop"
              note=".margin-rule, the cheapest and most on-brand texture available"
            >
              <div className="margin-rule">
                <p className="text-body-md text-ink-muted">
                  A single hairline at the content&rsquo;s inline start, echoing the logo.
                </p>
              </div>
            </StateCell>
            <StateCell state="default" provenance="prop" note=".sticker, decorative badges only">
              <span className="sticker rounded-sm bg-pastel-amber px-2.5 py-1 text-eyebrow text-pastel-amber-ink">
                7 day streak
              </span>
            </StateCell>
            <StateCell state="default" provenance="prop" note="The paper grain is on this page">
              <p className="text-hand text-ink-muted">
                Marginalia lives here, and nowhere that matters.
              </p>
            </StateCell>
          </ComponentSection>
        </Group>

        <Group title="Forms">
          <ComponentSection
            name="Button"
            summary="Solid fill, 8px radius, scale(0.98) press. Never a pill. Loading keeps the label rendered so the button does not resize mid-submit."
          >
            <StateGrid
              render={(s) => (
                <Button
                  variant="primary"
                  disabled={s === "disabled"}
                  loading={s === "loading"}
                  icon={s === "default" ? <Plus size={16} /> : undefined}
                >
                  Mark paper
                </Button>
              )}
              notes={{
                error: "Button has no error styling of its own: the error belongs to the form",
                success: "Same. A button reports outcome through a toast, not through its own fill",
              }}
            />
          </ComponentSection>

          <ComponentSection
            name="Button variants"
            summary="Primary is the one obvious action on a screen. Ink is for dark panels. Secondary is the default, ghost is for Cancel."
          >
            <StateCell state="default" provenance="prop" note="All four, at rest">
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" size="sm">Primary</Button>
                <Button variant="ink" size="sm">Ink</Button>
                <Button variant="secondary" size="sm">Secondary</Button>
                <Button variant="ghost" size="sm">Ghost</Button>
              </div>
            </StateCell>
            <StateCell state="default" provenance="prop" note="Three sizes">
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm">Small</Button>
                <Button size="md">Medium</Button>
                <Button size="lg">Large</Button>
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Input"
            summary="Visible label always. Placeholder-as-label is forbidden. Errors render inline and adjacent to the field, never only at the top of the form."
          >
            <StateGrid
              render={(s) => (
                <Input
                  label="Paper code"
                  placeholder="0625_w24_qp_41"
                  hint={s === "default" ? "Found on the front page" : undefined}
                  disabled={s === "disabled"}
                  state={s === "loading" || s === "success" ? s : undefined}
                  error={s === "error" ? "We don't recognise that paper code" : undefined}
                  leadingIcon={s === "default" ? <MagnifyingGlass size={16} /> : undefined}
                />
              )}
            />
          </ComponentSection>

          <ComponentSection
            name="File drop"
            summary="A drop target that is also a real, focusable file input, so it works from the keyboard and on a phone where there is nothing to drop. Active is the drag-over state; success is a chosen file."
          >
            <StateGrid
              render={(s) => (
                <FileDrop
                  // The id must differ per cell: eight `<label for>` pairs
                  // sharing one id would all point at the first input, so
                  // clicking any cell would open the first cell's picker.
                  id={`preview-file-drop-${slug(s)}`}
                  label="Scanned paper"
                  labelNote="required"
                  accept="application/pdf,image/*"
                  file={s === "success" ? PREVIEW_FILE : null}
                  onFileChange={() => {}}
                  disabled={s === "disabled"}
                  busy={s === "loading"}
                  hint={s === "default" ? "One paper per upload" : undefined}
                  error={s === "error" ? "That file is bigger than 25 MB" : undefined}
                />
              )}
              notes={{
                // Said plainly rather than faked: the other seven cells show
                // the state they claim, and a cell that quietly showed the
                // resting target under an "active" label would be the kind of
                // evidence-shaped non-evidence this build keeps finding.
                active:
                  "Drag-over is JavaScript state, not a pseudo-class, so `Force` cannot pin it and this cell shows the target at rest. The accent rule and wash are exercised on the real screen.",
              }}
            />
          </ComponentSection>

          <ComponentSection name="Textarea" summary="Same conventions as Input, for longer answers.">
            <StateGrid
              render={(s) => (
                <Textarea
                  label="Note to your teacher"
                  disabled={s === "disabled"}
                  state={s === "loading" || s === "success" ? s : undefined}
                  error={s === "error" ? "Keep this under 500 characters" : undefined}
                />
              )}
            />
          </ComponentSection>

          <ComponentSection
            name="Select"
            summary="A native select styled to match Input. Deliberately not a custom listbox: the native control is keyboard and screen-reader correct everywhere, and it is the right control on a phone."
          >
            <StateGrid
              render={(s) => (
                <Select
                  label="Subject"
                  disabled={s === "disabled"}
                  state={s === "loading" || s === "success" ? s : undefined}
                  error={s === "error" ? "Pick a subject to continue" : undefined}
                >
                  <option>Physics</option>
                  <option>Mathematics</option>
                  <option>Chemistry</option>
                </Select>
              )}
            />
          </ComponentSection>

          <ComponentSection
            name="Checkbox, Radio and Switch"
            summary="The radio dot and the switch thumb are circular by platform convention, which DESIGN.md §6 explicitly exempts from the pill ban."
          >
            <StateCell state="default" provenance="prop">
              <div className="flex flex-col gap-3">
                <Checkbox label="Email me when marking finishes" />
                <Checkbox label="Already checked" defaultChecked />
                <Checkbox label="Disabled" disabled />
              </div>
            </StateCell>
            <StateCell state="error" provenance="prop">
              <Checkbox label="Accept the terms" error="You need to accept this to continue" />
            </StateCell>
            <StateCell state="default" provenance="prop">
<RadioDemo name="variant" />
            </StateCell>
            <StateCell state="success" provenance="prop" note="State glyph sits on the legend, because the state belongs to the group">
<RadioDemo name="variant-ok" state="success" />
            </StateCell>
            <StateCell state="error" provenance="prop">
<RadioDemo name="variant-err" error="Pick a variant" />
            </StateCell>
            <StateCell state="default" provenance="prop">
              <div className="flex flex-col gap-3">
                <Switch label="Weekly summary" />
                <Switch label="On by default" defaultChecked />
                <Switch label="Disabled" disabled />
              </div>
            </StateCell>
          </ComponentSection>
        </Group>

        <Group title="Display">
          <ComponentSection
            name="Badge and subject tags"
            summary="The one place a pill is legal. Subject colours are fixed by DESIGN.md §3.8 and never picked at a call site."
          >
            <StateCell state="default" provenance="prop" note="Semantic tones">
              <div className="flex flex-wrap gap-2">
                <Badge tone="ok">Marked</Badge>
                <Badge tone="warn">Needs review</Badge>
                <Badge tone="err">Failed</Badge>
                <Badge tone="info">Queued</Badge>
              </div>
            </StateCell>
            <StateCell state="default" provenance="prop" note="Subject tags, colour fixed by subject">
              <div className="flex flex-wrap gap-2">
                <SubjectTag subject="Mathematics" />
                <SubjectTag subject="Physics" />
                <SubjectTag subject="Chemistry" />
                <SubjectTag subject="Biology" />
                <SubjectTag subject="English" />
                <SubjectTag subject="Sociology" />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Avatar, Kbd and ProgressBar"
            summary="Avatars are squircles, not circles: a circle has to keep meaning 'status', not 'person'."
          >
            <StateCell state="default" provenance="prop" note="Squircle, three sizes, initials fallback">
              <div className="flex items-center gap-3">
                <Avatar name="Yassin Diab" size="sm" />
                <Avatar name="Habeeby" size="md" />
                <Avatar name="Nour Ahmed" size="lg" />
              </div>
            </StateCell>
            <StateCell state="default" provenance="prop">
              <div className="flex items-center gap-2">
                <Kbd>Ctrl</Kbd>
                <Kbd>K</Kbd>
              </div>
            </StateCell>
            <StateCell state="default" provenance="prop" note="Determinate, animates transform not width">
              <div className="w-full">
                <ProgressBar value={62} label="Syllabus covered" />
              </div>
            </StateCell>
            <StateCell state="loading" provenance="prop" note="Indeterminate">
              <div className="w-full">
                <ProgressBar indeterminate ariaLabel="Marking in progress" />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Table"
            summary="Sunk header, hairline row dividers, tabular numbers right-aligned so a column of marks always lines up."
          >
            <StateCell state="default" provenance="prop">
              <div className="w-full">
                <Table>
                  <THead>
                    <TR>
                      <TH>Paper</TH>
                      <TH numeric>Mark</TH>
                    </TR>
                  </THead>
                  <TBody>
                    <TR>
                      <TD>0625_w24_qp_41</TD>
                      <TD numeric>63/80</TD>
                    </TR>
                    <TR>
                      <TD>0625_s23_qp_22</TD>
                      <TD numeric>37/40</TD>
                    </TR>
                  </TBody>
                </Table>
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Skeleton"
            summary="Layout-matching, so nothing shifts when the real content arrives. The Phase 1 audit found no skeleton component existed anywhere in the product."
          >
            <StateCell state="loading" provenance="prop">
              <div className="flex w-full flex-col gap-3">
                <SkeletonLine />
                <SkeletonText lines={3} />
              </div>
            </StateCell>
            <StateCell state="loading" provenance="prop">
              <div className="flex w-full items-center gap-3">
                <SkeletonCircle />
                <SkeletonBlock className="h-16 flex-1" />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="ChartFrame"
            summary="The frame and its mandatory empty state. Charts themselves are Phase 5; DESIGN.md §11 requires every chart to have an empty-data state, so the frame enforces it structurally."
          >
            <StateCell state="default" provenance="prop">
              <div className="w-full">
                <ChartFrame title="Predicted grade" subtitle="Last six papers">
                  <div className="dotted-bg h-28 rounded-md border border-rule" />
                </ChartFrame>
              </div>
            </StateCell>
            <StateCell state="default" provenance="prop" note="isEmpty always wins over children">
              <div className="w-full">
                <ChartFrame title="Predicted grade" isEmpty>
                  <div className="h-28" />
                </ChartFrame>
              </div>
            </StateCell>
          </ComponentSection>
        </Group>

        <Group title="Overlays">
          <ComponentSection
            name="Tabs, Popover, Modal and Toast"
            summary="Floating layers are the only place a shadow is permitted, and only the ultra-diffuse one. Everything here is keyboard-operable."
          >
            <StateCell state="default" provenance="live" note="Arrow keys move between tabs">
              <TabsDemo />
            </StateCell>
            <StateCell state="default" provenance="live" note="Click to open, Escape to close">
              {/* P3 gate: this destructured the whole render argument as
                  `triggerProps` and spread it, so the button received
                  `open={false}` and a nested `triggerProps` object as DOM
                  attributes, and received none of the ref, onClick or ARIA the
                  popover supplies. React warned about it in the console and
                  the cell could not be opened at all — a "click to open" demo
                  that did not open, sitting on the page that exists to prove
                  the kit works. `renderTrigger` yields
                  `{ open, triggerProps }`; only the latter is spread. */}
              <Popover
                renderTrigger={({ triggerProps }) => (
                  <Button size="sm" {...triggerProps}>
                    Open popover
                  </Button>
                )}
              >
                <p className="text-body-sm text-ink-muted">
                  Confidence is how sure the marker is, not how right it is.
                </p>
              </Popover>
            </StateCell>
            <StateCell state="default" provenance="live" note="Focus is trapped and restored on close">
              <ModalDemo />
            </StateCell>
            <StateCell state="default" provenance="live" note="Auto-dismisses, pauses on hover">
              <ToastDemo />
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="ErrorState"
            summary="Active voice, names what happened and what to do, and offers a retry. Amber by default (PRODUCT.md's accessibility section: avoid red-heavy error states). The Phase 1 audit found no error boundary existed anywhere; ErrorBoundary now wraps this same full-panel presentation. Loading/error primitives PR, part A merged the kit-only red variant that used to live here (title/message/onRetry) into this component; compact below is what survived that merge."
          >
            <StateCell state="error" provenance="prop">
              <div className="w-full">
                <ErrorState
                  heading="We couldn't load your papers"
                  body="The connection dropped partway through. Your work is safe."
                  action={{ label: "Try again", onClick: () => undefined }}
                />
              </div>
            </StateCell>
            <StateCell
              state="error"
              provenance="prop"
              note="Compact: a small inline slot for a single field or table cell, not a whole panel. Retry renders as an underlined text button."
            >
              <div className="w-full">
                <ErrorState
                  compact
                  heading="Couldn't save this answer"
                  body="Check your connection and try again."
                  action={{ label: "Retry", onClick: () => undefined }}
                />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="QueryState"
            summary="Loading/error primitives PR, part A. Takes a react-query result and renders the matching skeleton, error or empty view without every screen composing that switch by hand; see student Overview.tsx for the reference conversion. The cells below use hand-built query objects rather than a live query, so every state is reachable on demand."
          >
            <StateCell state="loading" provenance="prop" note="Skeleton is caller-supplied, from loading-shapes.tsx">
              <div className="w-full">
                <QueryState<QueryStateDemoData>
                  query={QUERY_STATE_DEMO.pending}
                  skeleton={<PanelSkeleton />}
                  error={{ heading: "Couldn't load the demo panel" }}
                >
                  {(data) => <QueryStateDemoPanel rows={data.rows} />}
                </QueryState>
              </div>
            </StateCell>
            <StateCell
              state="error"
              provenance="prop"
              note="error.body omitted, so it falls back to describeQueryFailure(query.error) — here a fake 503"
            >
              <div className="w-full">
                <QueryState<QueryStateDemoData>
                  query={QUERY_STATE_DEMO.error}
                  skeleton={<PanelSkeleton />}
                  error={{ heading: "Couldn't load the demo panel" }}
                >
                  {(data) => <QueryStateDemoPanel rows={data.rows} />}
                </QueryState>
              </div>
            </StateCell>
            <StateCell
              state="error"
              provenance="prop"
              note="error.secondaryAction: a second way out, for a failure a retry cannot fix. A detail route opened with a bad id retries into the same failure every time."
            >
              <div className="w-full">
                <QueryState<QueryStateDemoData>
                  query={QUERY_STATE_DEMO.error}
                  skeleton={<PanelSkeleton />}
                  error={{
                    heading: "Couldn't load the demo panel",
                    secondaryAction: { label: "Back to the list", onClick: () => {} },
                  }}
                >
                  {(data) => <QueryStateDemoPanel rows={data.rows} />}
                </QueryState>
              </div>
            </StateCell>
            <StateCell
              state="error"
              provenance="prop"
              note="error.compact: the inline treatment, for a failure that is one line inside a page that still works. Shown beside the full panel above for scale."
            >
              <div className="w-full">
                <QueryState<QueryStateDemoData>
                  query={QUERY_STATE_DEMO.error}
                  skeleton={<PanelSkeleton />}
                  error={{ heading: "Couldn't load the demo panel", compact: true }}
                >
                  {(data) => <QueryStateDemoPanel rows={data.rows} />}
                </QueryState>
              </div>
            </StateCell>
            <StateCell
              state="loading"
              provenance="prop"
              note="An enabled: false query: status pending, fetchStatus idle. Renders the idle prop, not a skeleton that would never resolve on its own."
            >
              <div className="w-full">
                <QueryState<QueryStateDemoData>
                  query={QUERY_STATE_DEMO.idle}
                  skeleton={<PanelSkeleton />}
                  idle={
                    <EmptyState
                      heading="Pick a class to see this panel"
                      body="This loads once a class is selected above."
                    />
                  }
                  error={{ heading: "Couldn't load the demo panel" }}
                >
                  {(data) => <QueryStateDemoPanel rows={data.rows} />}
                </QueryState>
              </div>
            </StateCell>
            <StateCell
              state="default"
              provenance="prop"
              note="isEmpty true and an empty prop supplied, so it wins over children"
            >
              <div className="w-full">
                <QueryState<QueryStateDemoData>
                  query={QUERY_STATE_DEMO.empty}
                  skeleton={<PanelSkeleton />}
                  error={{ heading: "Couldn't load the demo panel" }}
                  isEmpty={(data) => data.rows.length === 0}
                  empty={
                    <EmptyState
                      heading="Nothing here yet"
                      body="Rows appear here once the demo panel has something to show."
                    />
                  }
                >
                  {(data) => <QueryStateDemoPanel rows={data.rows} />}
                </QueryState>
              </div>
            </StateCell>
            <StateCell state="success" provenance="prop">
              <div className="w-full">
                <QueryState<QueryStateDemoData>
                  query={QUERY_STATE_DEMO.success}
                  skeleton={<PanelSkeleton />}
                  error={{ heading: "Couldn't load the demo panel" }}
                >
                  {(data) => <QueryStateDemoPanel rows={data.rows} />}
                </QueryState>
              </div>
            </StateCell>
          </ComponentSection>
        </Group>

        {/* Phase 3's additions. Listed here for the same reason as everything
            above: a component that is never rendered side by side with its own
            states is a component whose states are assumed rather than seen. */}
        <Group title="Navigation and first run">
          <ComponentSection
            name="Breadcrumbs"
            summary="P3.1 / D1.5's back affordance for the teacher and parent portals. Collapses below sm to a single back link so it stays one line and one tap on a phone. Resize the window to see it switch."
          >
            <StateCell
              state="default"
              provenance="prop"
              note="Full trail. Every crumb but the last links somewhere the router mounts."
            >
              <div className="w-full">
                <Breadcrumbs
                  collapse={false}
                  items={[
                    { label: "Overview", to: "/teacher" },
                    { label: "Classes", to: "/teacher/classes" },
                    { label: "This class", to: "/teacher/classes/demo" },
                    { label: "Analytics" },
                  ]}
                />
              </div>
            </StateCell>
            <StateCell
              state="default"
              provenance="live"
              note="Collapsing form. Narrow the viewport past 640px to see it become a back link."
            >
              <div className="w-full">
                <Breadcrumbs
                  items={[
                    { label: "Overview", to: "/teacher" },
                    { label: "Classes", to: "/teacher/classes" },
                    { label: "This class" },
                  ]}
                />
              </div>
            </StateCell>
            <StateCell
              state="disabled"
              provenance="prop"
              note="A single crumb renders nothing: no claim about where you are beats a wrong one."
            >
              <div className="w-full">
                <Breadcrumbs items={[{ label: "Overview" }]} />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="NavDrawerTrigger"
            summary="The menu button that opens the mobile nav drawer. Below 820px (student) and 768px (teacher) it is the only entry point to navigation that exists, so its 44x44 target and accessible name are load-bearing, not polish."
          >
            <StateCell state="default" provenance="prop">
              <NavDrawerTrigger onClick={() => undefined} label="Open navigation" />
            </StateCell>
            <StateCell
              state="hover"
              provenance="live"
              note="Hover and focus it with the keyboard to see both treatments"
            >
              <NavDrawerTrigger onClick={() => undefined} label="Open navigation" />
            </StateCell>
            <StateCell state="active" provenance="live" note="Press and hold: scale(0.98)">
              <NavDrawerTrigger onClick={() => undefined} label="Open navigation" />
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="SkipLink"
            summary="Visually hidden until focused, then a real visible control. Tab into the cell below. Both portals put 8 to 11 nav destinations before the content in DOM order, and re-render them on every route, so without this a keyboard user re-tabs the whole sidebar on every navigation."
          >
            <StateCell
              state="focus-visible"
              provenance="live"
              note="Click here then press Tab. It is genuinely invisible until focused."
            >
              <div className="relative h-16 w-full">
                <SkipLink />
                <span className="text-body-sm text-ink-faint">Tab into this cell</span>
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="GettingStarted"
            summary="P3.2's first-run panel, replacing a single centred EmptyState on the student and teacher dashboards. No endpoint reports per-step onboarding progress, so `done` is only ever passed where the caller holds evidence; `later` steps carry no tick and no action deliberately."
          >
            <StateCell
              state="default"
              provenance="prop"
              note="The real student first-run content. No step is `done`, because nothing on that screen can observe one."
            >
              <div className="w-full">
                <GettingStarted
                  heading="Let's get your first paper marked"
                  body="Lemely works from your own past papers. Mark one and this page fills in on its own."
                  steps={[
                    {
                      title: "Correct your first paper",
                      body: "Photograph or upload a paper you have already sat.",
                      status: "now",
                      to: "/student/correct",
                      actionLabel: "Correct a paper",
                    },
                    {
                      title: "See where you stand",
                      body: "Your predicted grade is measured against the real Cambridge grade boundaries.",
                      status: "later",
                    },
                  ]}
                  footnote="Nothing here is filled in with sample data."
                />
              </div>
            </StateCell>
            <StateCell
              state="success"
              provenance="prop"
              note="A completed step. The word 'Done' is rendered beside the tick: colour alone carries nothing."
            >
              <div className="w-full">
                <GettingStarted
                  heading="Start with one class"
                  body="Everything else in Lemely hangs off a class."
                  steps={[
                    {
                      title: "Create your first class",
                      body: "Give it a name and a subject code.",
                      status: "done",
                    },
                    {
                      title: "Mark a set of papers",
                      body: "Upload scanned scripts and Lemely marks them against the official scheme.",
                      status: "now",
                      to: "/teacher/grading",
                      actionLabel: "Open grading",
                    },
                    {
                      title: "Look at what marking flagged",
                      body: "Anything the marker was unsure about goes to your review queue.",
                      status: "later",
                    },
                  ]}
                />
              </div>
            </StateCell>
          </ComponentSection>
        </Group>

        {/* PR 2 part A1. Nine full-page states, one `ComponentSection` each,
            all shown in the PORTAL frame: the standalone frame is
            `min-h-screen` and would blow out the grid this page lays cells
            out in. `NotFound`/`PortalNotFound` (and every future caller) pick
            `frame="standalone"` at the real top-level routes; the frame prop
            itself is exercised nowhere here, on purpose, since a screenshot
            of a full viewport is not a state cell. */}
        <Group title="Full-page states">
          <ComponentSection
            name="Not found"
            summary="`not-found`. What `NotFound`/`PortalNotFound` render for a genuinely unmatched path. Amber/neutral tone throughout this family, never red (DESIGN.md's accessibility guidance)."
          >
            <StateCell state="default" provenance="prop">
              <div className="w-full">
                <FullPageState variant="not-found" frame="portal" />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Crash"
            summary="`crash`. What `NotFound` renders when `useRouteError` returns something other than a 404 Response, i.e. a render actually threw. Primary goes home, secondary reloads."
          >
            <StateCell state="error" provenance="prop">
              <div className="w-full">
                <FullPageState variant="crash" frame="portal" />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Offline"
            summary="No primary action — there is nothing to navigate to while offline — and the waiting line pulses to show the page is still listening, not stalled. `onRetry` is supplied here only so the secondary Try again control has something to render; the real caller wires it to whatever check brought the reader here."
          >
            <StateCell state="error" provenance="prop" note="The waiting line is role=status, polite, not alert">
              <div className="w-full">
                <FullPageState variant="offline" frame="portal" onRetry={() => undefined} />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="New version"
            summary="`new-version`. A stale build caught by the chunk-load guard: reload picks up the new one and nothing typed is lost, so this is the one variant that gets straight to a single reload action with no secondary."
          >
            <StateCell state="default" provenance="prop">
              <div className="w-full">
                <FullPageState variant="new-version" frame="portal" />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Session ended"
            summary="`session-ended`. `returnTo` (omitted here) carries the reader back to where they were once they sign back in, via `/login?next=...`."
          >
            <StateCell state="error" provenance="prop">
              <div className="w-full">
                <FullPageState variant="session-ended" frame="portal" />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="No access"
            summary="`no-access`. A signed-in reader on the wrong role's route. Home is role-aware (`portalPathForRole`), so this always offers somewhere the reader can actually go, never the page they were just refused."
          >
            <StateCell state="error" provenance="prop">
              <div className="w-full">
                <FullPageState variant="no-access" frame="portal" />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Service trouble"
            summary="`service-trouble`. `health` is optional and caller-supplied (no polling happens in this component); omitted, the status row simply does not render. Both reachable statuses shown below; `unknown` renders the same row with a neutral rule-coloured dot."
          >
            <StateCell state="error" provenance="prop" note="health.status = 'not-responding'">
              <div className="w-full">
                <FullPageState
                  variant="service-trouble"
                  frame="portal"
                  onRetry={() => undefined}
                  health={{ status: "not-responding", checkedSecondsAgo: 12 }}
                />
              </div>
            </StateCell>
            <StateCell state="error" provenance="prop" note="health.status = 'responding' — the service answered, but this page still failed to load">
              <div className="w-full">
                <FullPageState
                  variant="service-trouble"
                  frame="portal"
                  onRetry={() => undefined}
                  health={{ status: "responding", checkedSecondsAgo: 3 }}
                />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Too many requests"
            summary="`too-many-requests`. `retryAfterSeconds` is caller-owned countdown state, re-rendered every second; this component only formats it and disables the retry control while it is still above zero. No timer runs inside it."
          >
            <StateCell state="error" provenance="prop" note="retryAfterSeconds=42 — retry disabled">
              <div className="w-full">
                <FullPageState
                  variant="too-many-requests"
                  frame="portal"
                  retryAfterSeconds={42}
                  onRetry={() => undefined}
                />
              </div>
            </StateCell>
            <StateCell state="error" provenance="prop" note="retryAfterSeconds=0 — retry enabled">
              <div className="w-full">
                <FullPageState
                  variant="too-many-requests"
                  frame="portal"
                  retryAfterSeconds={0}
                  onRetry={() => undefined}
                />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Slow load"
            summary="`slow-load`. Copy-only — no `DoodleKind` of its own — for a page that is taking unusually long rather than one that has actually failed. Renders the animated `Mark` (§9.2's one documented stroke-dashoffset exception) instead of a `Doodle`."
          >
            <StateCell state="loading" provenance="prop">
              <div className="w-full">
                <FullPageState variant="slow-load" frame="portal" />
              </div>
            </StateCell>
          </ComponentSection>
        </Group>

        {/* PR 2 part D. The loading tiers and the two recovery surfaces. Each
            tier is pinned with `tierStyle` rather than waited for, since a
            preview cell that changes on its own after five seconds is not a
            state cell. The banner and the toasts are their presentational
            halves: `OfflineBannerView` (no `useOnlineStatus`) and `ToastCard`
            (no timer, no provider), fed the very copy `RecoveryEffects` fires. */}
        <Group title="Loading and recovery">
          <ComponentSection
            name="Loading tiers"
            summary="`RouteFallback`, the Suspense fallback around every portal Outlet and lazy screen. Paper only for the first 200 ms, then the layout skeleton, then after 5 s the slow-load state paints over it. Both thresholds are the `--loading-tier-skeleton` and `--loading-tier-slow` tokens; the pre-mount shell in index.html stages on the same two numbers."
          >
            <StateCell state="loading" provenance="prop" note="Tier 1, 0 to 200 ms: paper only">
              <div className="min-h-40 w-full" style={tierStyle(HELD, HELD)}>
                <RouteFallback frame="content" />
              </div>
            </StateCell>
            <StateCell state="loading" provenance="prop" note="Tier 2, 200 ms to 5 s: layout skeleton">
              <div className="w-full" style={tierStyle("0s", HELD)}>
                <RouteFallback frame="content" />
              </div>
            </StateCell>
            <StateCell state="loading" provenance="prop" note="Tier 3, after 5 s: slow load">
              <div className="w-full" style={tierStyle("0s", "0s")}>
                <RouteFallback frame="content" />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Offline banner"
            summary="`OfflineBanner`, mounted inside every portal layout's main. A page that already has content keeps it and gets this strip above it while the browser is offline; the page refetches by itself on reconnect. Polite status, amber and neutral, never red."
          >
            <StateCell state="error" provenance="prop" note="OfflineBannerView, the hookless half">
              <div className="w-full">
                <OfflineBannerView onRetry={() => undefined} />
              </div>
            </StateCell>
          </ComponentSection>

          <ComponentSection
            name="Recovery toasts"
            summary="The two announcements `RecoveryEffects` fires: on the offline-to-online transition after every errored query refetches, and once on the first render after the stale-chunk guard reloaded the page for a new build. Rendered here as `ToastCard`, the toast's markup without its auto-dismiss clock."
          >
            <StateCell state="success" provenance="prop" note="After a reconnect">
              <div className="flex w-full max-w-sm flex-col gap-2">
                <ToastCard {...RECONNECTED_TOAST} onDismiss={() => undefined} />
              </div>
            </StateCell>
            <StateCell state="default" provenance="prop" note="After a stale-chunk reload">
              <div className="flex w-full max-w-sm flex-col gap-2">
                <ToastCard {...UPDATED_TOAST} onDismiss={() => undefined} />
              </div>
            </StateCell>
          </ComponentSection>
        </Group>
      </main>
    </div>
  )
}
