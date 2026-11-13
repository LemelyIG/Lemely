import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")
const css = read("index.css")

describe("BottomSheetSurface (Task 6)", () => {
  const src = read("components/ui/bottom-sheet.tsx")
  it("drags only from the grabber and header region, never from content text", () => {
    expect(src).toContain("data-sheet-drag-region")
    expect(src).toContain('closest("[data-sheet-drag-region]")')
  })
  it("leaves header buttons, links and fields their own click", () => {
    expect(src).toContain('const INTERACTIVE = "button, a, input, select, textarea, [role=button]"')
    expect(src).toMatch(/target\.closest\(INTERACTIVE\)/)
    expect(src).toContain("e.button > 0")
  })
  it("the sheet follows the finger with no transition while dragging", () => {
    expect(src).toContain('setAttribute("data-dragging", "")')
    expect(src).toContain('removeAttribute("data-dragging")')
  })
  it("the scale-back hook is guarded on the phone media query", () => {
    expect(src).toMatch(/useSheetScaleBack[\s\S]*window\.matchMedia\(PHONE_MEDIA\)\.matches/)
  })
  it("Android-only haptic on snap", () => {
    expect(src).toContain('nativeHaptic("tap")')
  })
  it("iOS keyboard: positions by visualViewport", () => {
    expect(src).toContain("window.visualViewport")
    expect(src).toContain("--lm-keyboard-inset")
  })
})

describe("sheet CSS", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: sheets"))
  it("top radius is the card radius; grabber sizes per platform", () => {
    expect(block).toMatch(/\.lm-sheet \{[^}]*border-start-start-radius: var\(--radius-card\);[^}]*border-start-end-radius: var\(--radius-card\);/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-sheet-grabber \{[^}]*inline-size: var\(--native-grabber-w-ios\);[^}]*block-size: var\(--native-grabber-h-ios\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-sheet-grabber \{[^}]*inline-size: var\(--native-grabber-w-android\);[^}]*block-size: var\(--native-grabber-h-android\)/)
  })
  it("iOS scales the page back at the large detent, pivoting on the visible top; reduced motion keeps it instant", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\]\[data-sheet-depth\] #root \{[^}]*scale: var\(--native-sheet-scale-back\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] #root \{[^}]*transform-origin: 50% calc\(var\(--native-sheet-sy, 0px\) \+ env\(safe-area-inset-top\)\)/)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*#root[\s\S]*transition: none/)
  })
  it("per-platform large detent, motion and grabber (preview 4447a571)", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \{[^}]*--native-sheet-large: var\(--native-sheet-large-ios\);[^}]*--native-sheet-dur: var\(--dur-sheet-ios\);[^}]*--native-sheet-ease: var\(--ease-ios-spring\)/)
    expect(block).toMatch(/:root\[data-platform="android"\] \{[^}]*--native-sheet-large: var\(--native-sheet-large-android\);[^}]*--native-sheet-dur: var\(--dur-sheet-android\);[^}]*--native-sheet-ease: var\(--ease-m3-emphasized-decelerate\)/)
    expect(block).toMatch(/\.lm-sheet \{[^}]*background: var\(--md-surface-container-low\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-sheet-grabber \{[^}]*margin-block: var\(--native-grabber-gap-ios\)/)
  })
  it("no transition while dragging; the drag region is a finger tall and owns touch-action", () => {
    expect(block).toMatch(/\.lm-sheet\[data-dragging\] \{[^}]*transition: none/)
    expect(block).toMatch(/\[data-sheet-drag-region\] \{[^}]*min-block-size: var\(--native-sheet-drag-min\);[^}]*touch-action: none/)
    expect(block).toMatch(/:root\[data-platform="ios"\] \{[^}]*--native-sheet-drag-min: var\(--native-iconbtn-ios\)/)
    expect(block).not.toMatch(/\.lm-sheet-grabber \{[^}]*touch-action/)
    expect(block).toMatch(/\.lm-sheet-grabber \{[^}]*border-radius: var\(--radius-pill\)/)
  })
  it("the iOS scale-back rules are phone-only", () => {
    expect(block).toMatch(/@media \(max-width: 720px\) \{\s*:root\[data-platform="ios"\] #root \{[\s\S]*?\[data-sheet-depth\] body \{[^}]*\}\s*\}/)
  })
  it("the sheet sits above the keyboard", () => {
    expect(block).toContain("bottom: var(--lm-keyboard-inset, 0px)")
  })
})

describe("ui/sheet.tsx (Task 6)", () => {
  const src = read("components/ui/sheet.tsx")
  it("bottom and adaptive sheets use BottomSheetSurface on the native frame", () => {
    expect(src).toContain("useNativeFrame()")
    expect(src).toMatch(/native && \(side === "bottom" \|\| side === "adaptive"\)/)
    expect(src).toContain("<BottomSheetSurface")
  })
  it("does not forward the desktop panel class to the native surface; the body carries the inset", () => {
    const native = src.slice(src.indexOf("<BottomSheetSurface"), src.indexOf("</BottomSheetSurface>"))
    expect(native).not.toContain("className={className}")
    expect(native).toContain('bodyClassName="p-6"')
    expect(native).toContain("tabIndex={-1}")
  })
})

describe("Modal on the native frame (Task 7)", () => {
  const src = read("components/ui/modal.tsx")
  it("keeps one dialog contract and only swaps the surface", () => {
    expect(src).toContain("useNativeFrame()")
    expect(src.match(/role: "dialog"/g)?.length).toBe(1)
    expect(src).not.toContain('role="dialog"')
    expect(src).toContain("<BottomSheetSurface")
    expect(src).toMatch(/detents=\{size === "lg" \? \["medium", "large"\] : \["content"\]\}/)
    expect(src).toMatch(/dismissible=\{dismissible\}/)
  })
  it("size lg opens at medium and drags to large (D10)", () => {
    expect(src).toMatch(/initialDetent=\{size === "lg" \? "medium" : "content"\}/)
  })
  it("call sites are untouched: the public props are unchanged", () => {
    expect(src).toMatch(/export interface ModalProps \{[\s\S]*open: boolean[\s\S]*onClose: \(\) => void[\s\S]*title: ReactNode/)
  })
})

describe("ConfirmModal (Task 7)", () => {
  const src = read("components/ui/confirm-modal.tsx")
  it("iOS native uses an action sheet with Cancel in its own group", () => {
    expect(src).toMatch(/platform === "ios"[\s\S]*presentation="action-sheet"/)
    expect(src).toContain("lm-action-sheet-cancel")
  })
  it("the action sheet's visible title is aria-hidden; Modal's sr-only copy labels the dialog", () => {
    expect(src).toMatch(/<div aria-hidden="true"[^>]*>\s*<p[^>]*>\{title\}<\/p>/)
    const modal = read("components/ui/modal.tsx")
    expect(modal).toMatch(/presentation === "action-sheet"[\s\S]*<h2 id=\{titleId\} className="sr-only">/)
    expect(modal).toMatch(/<p id=\{descriptionId\} className="sr-only">/)
  })
  it("stays non-dismissible (no scrim close, no drag, no grabber)", () => {
    expect(src).toContain("dismissible={false}")
  })
  it("Modal focuses [data-autofocus] before the first focusable, and Cancel carries it", () => {
    const modal = read("components/ui/use-dialog-focus.ts") // the focus code moved here in Task 9
    expect(modal).toMatch(/querySelector<HTMLElement>\(AUTOFOCUS_SELECTOR\)\s*\?\?\s*panel\?\.querySelector<HTMLElement>\(FOCUSABLE_SELECTOR\)/)
    expect(modal).toContain('const AUTOFOCUS_SELECTOR = "[data-autofocus]"')
    expect(src).toMatch(/lm-action-sheet-cancel"\s*data-autofocus/)
    // The destructive row must not carry it.
    expect(src.match(/data-autofocus/g)).toHaveLength(1)
  })
  it("the action-sheet body is a column with a gap and a bottom padding token", () => {
    expect(css).toMatch(/\.lm-action-sheet-body \{[^}]*flex-direction: column;[^}]*gap: var\(--space-2\);[^}]*padding-bottom: var\(--space-2\)/)
    expect(read("components/ui/modal.tsx")).toContain('"lm-action-sheet-body"')
  })
  it("action-sheet rows use the native tokens", () => {
    expect(css).toMatch(/\.lm-action-sheet-row \{[^}]*min-block-size: var\(--native-action-row-h\)/)
    expect(css).toMatch(/\.lm-action-sheet-cancel \{[^}]*font-weight: 600/)
  })
})

describe("shell panels on the native frame (Task 8)", () => {
  for (const file of ["components/shell/NotificationsPanel.tsx", "components/shell/AccountPanel.tsx"]) {
    const src = read(file)
    it(`${file}: one body, two frames`, () => {
      expect(src).toContain("useNativeFrame()")
      expect(src).toMatch(/native \? \(\s*<PanelSheet/)
      expect(src).toContain("<DropdownMenu.Root modal={false}>")
    })
    it(`${file}: the sheet rows are list rows`, () => {
      expect(src).toContain("<ListRow")
      expect(src).toContain("<ListGroup")
    })
  }
  it("PanelSheet reuses Modal's dialog contract instead of copying it", () => {
    const src = read("components/shell/PanelSheet.tsx")
    expect(src).toMatch(/<Modal\b[^>]*open=\{open\}[^>]*size="md"/)
    expect(src).toContain('aria-haspopup="dialog"')
    expect(src).toContain("aria-expanded={open}")
    expect(src).not.toContain("FOCUSABLE_SELECTOR")
    expect(src).not.toContain('role="dialog"')
  })
  it("SettingsModal is a medium/large sheet on native (preview data-detents) and keeps routing close", () => {
    const src = read("portals/settings/SettingsModal.tsx")
    expect(src).toContain("useNativeFrame()")
    expect(src).toMatch(/detents=\{\["medium", "large"\]\}/)
    expect(src).toMatch(/initialDetent="medium"/)
    expect(src).toMatch(/onDismiss=\{onClose\}/)
  })
  it("the native settings sheet drops the safe-area top padding; desktop keeps its dialog", () => {
    const src = read("portals/settings/SettingsModal.tsx")
    const nativeStart = src.indexOf("if (native) {")
    const desktopStart = src.indexOf('className="fixed inset-0 z-modal flex', nativeStart)
    expect(nativeStart).toBeGreaterThan(-1)
    expect(desktopStart).toBeGreaterThan(nativeStart)
    const nativeBranch = src.slice(nativeStart, desktopStart)
    expect(nativeBranch).not.toContain("safe-area-inset-top")
    expect(src).toContain("pt-[max(env(safe-area-inset-top),1rem)]")
  })
  it("sheet rows navigate first; the sheet closes when the location changes (Task 8 fix round 1)", () => {
    const sheet = read("components/shell/PanelSheet.tsx")
    expect(sheet).toContain("useLocation()")
    expect(sheet).toMatch(/\[location\.key, location\.state\]/)
    expect(sheet).toContain("lemelyDialog")
    for (const file of ["components/shell/NotificationsPanel.tsx", "components/shell/AccountPanel.tsx", "components/ui/list-group.tsx"]) {
      const src = read(file)
      expect(src, `${file} must not close the sheet from a row`).not.toContain("onNavigate")
      expect(src).not.toMatch(/\bclose\(\)/)
    }
  })
  it("native sheets share the dialog scrim: the Radix sheet agrees with Modal, desktop keeps bg-scrim", () => {
    expect(read("components/ui/sheet.tsx")).toMatch(/bg-scrim native:bg-scrim-dialog/)
    expect(read("components/ui/modal.tsx")).toContain("bg-scrim-dialog")
  })
  it("a notification title clamps at two lines in the sheet, like the desktop panel", () => {
    expect(read("components/shell/NotificationsPanel.tsx")).toContain("titleLines={2}")
    expect(read("components/ui/list-group.tsx")).toContain('titleLines === 2 ? "line-clamp-2" : "truncate"')
  })
  it("the Create sheet's eyebrow leaves no gap to manage on native: audit A hides it there, so the title leads", () => {
    expect(read("components/shell/TopBarSheets.tsx")).toMatch(/text-eyebrow text-on-surface-variant native:hidden/)
  })
})

describe("Popover and Select (Task 9, D4)", () => {
  it("Popover renders a sheet on native and keeps its render-prop API", () => {
    const src = read("components/ui/popover.tsx")
    expect(src).toContain("useNativeFrame()")
    expect(src).toContain("<BottomSheetSurface")
    expect(src).toMatch(/renderTrigger: \(props: PopoverRenderProps\) => ReactNode/)
  })
  it("one focus trap: Modal and the native Popover share useDialogFocus", () => {
    for (const f of ["components/ui/modal.tsx", "components/ui/popover.tsx"]) {
      expect(read(f), f).toContain("useDialogFocus(")
      expect(read(f), f).not.toContain("FOCUSABLE_SELECTOR =")
    }
    expect(read("components/ui/use-dialog-focus.ts")).toContain("FOCUSABLE_SELECTOR")
  })
  it("Select stays a native <select>: the OS picker is already the platform sheet", () => {
    const src = read("components/ui/select.tsx")
    expect(src).toMatch(/<select\b/)
    expect(src).not.toContain("BottomSheetSurface")
    expect(src).toContain("native frame D4")
  })
  it("the Notifications row spreads triggerProps.id so the native sheet's aria-labelledby resolves, and Popover keeps an aria-label fallback", () => {
    expect(read("portals/student/screens/Notifications.tsx")).toContain("id={triggerProps.id}")
    const pop = read("components/ui/popover.tsx")
    expect(pop).toContain('"aria-labelledby": triggerId')
    expect(pop).toContain('"aria-label": "More actions"')
  })
})
