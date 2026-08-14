import { readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

/**
 * Phase 6.1 `adapt` — the mobile non-negotiables that can be pinned statically.
 *
 * The geometric half of §6.1 lives in `scripts/adapt_audit.mjs`, which renders
 * all 35 registered surfaces at 320/375/414/768/1440 and measures. This file
 * covers the rules whose violation is visible in the source, plus one
 * regression pin that is the whole reason the phase found anything at all.
 *
 * THE PIN THAT MATTERS IS THE LAST ONE.
 *
 * `scripts/audit.mjs`'s `checkNoHorizontalScroll` opened with
 *
 *     if (scrollWidth <= clientWidth + 1) return null
 *
 * and Phase 2 had added `overflow-x: clip` to html and body — one of the very
 * non-negotiables this suite enforces. Clipping suppresses the scroll that
 * guard measured, so from that commit the function returned `null` for every
 * route at every breakpoint and the offender-walk beneath it was dead code.
 * Two correct-looking rules, one silently disabling the other; every "no
 * horizontal scroll at 320/375/1440" claim made after Phase 2 rests on it.
 *
 * That defect cannot be caught by asking whether a check exists, because it
 * did exist and it ran. It can only be caught by pinning the *shape* that made
 * it vacuous. Hence the last test.
 */

const CSS_PATH = join(process.cwd(), "src/index.css")
const CSS_RAW = readFileSync(CSS_PATH, "utf8")


const CSS = stripComments(CSS_RAW)

describe("§6.1 grid tracks", () => {
  /**
   * A bare `1fr` has an `auto` minimum, so a track holding one long unbroken
   * token refuses to shrink and pushes its row past the container. Because
   * html/body clip, that surfaces as content cut off the side rather than as a
   * scrollbar. `minmax(0, 1fr)` is the fix and the mission names it outright.
   */
  it("every named grid template sizes fractional tracks with minmax(0, …)", () => {
    const templates = [...CSS.matchAll(/grid-template-columns:\s*([^;]+);/g)].map((m) =>
      m[1].replace(/\s+/g, " ").trim(),
    )
    expect(templates.length).toBeGreaterThan(0)

    const offenders = templates.filter((tpl) => {
      // Strip the well-formed minmax() calls, then look for any surviving `fr`.
      const withoutMinmax = tpl.replace(/minmax\([^)]*\)/g, "")
      return /\d*\.?\d*fr/.test(withoutMinmax)
    })
    expect(offenders).toEqual([])
  })

  it("does not reintroduce grid-subjects-row, which had no call sites", () => {
    expect(CSS).not.toContain("grid-subjects-row")
  })
})

describe("§6.1 display headers wrap", () => {
  const RUNGS = [
    "text-display-hero",
    "text-display-xl",
    "text-display-lg",
    "text-display-md",
    "text-display-sm",
  ]

  /**
   * `anywhere`, never `break-word`. Only `anywhere` participates in min-content
   * sizing, which is what lets a heading inside a grid or flex track actually
   * shrink; `break-word` breaks the glyphs but leaves the track sized to the
   * unbroken word, so the overflow it is meant to prevent survives.
   */
  it("all five display rungs are covered by an overflow-wrap: anywhere rule", () => {
    const blocks = [...CSS.matchAll(/([^{}]+)\{([^}]*overflow-wrap:\s*anywhere[^}]*)\}/g)]
    const covered = new Set<string>()
    for (const [, selector] of blocks) {
      for (const rung of RUNGS) {
        if (new RegExp(`\\.${rung}\\b`).test(selector)) covered.add(rung)
      }
    }
    expect([...covered].sort()).toEqual([...RUNGS].sort())
  })

  /**
   * The data rungs are deliberately excluded. They carry marks, percentages and
   * XP, where a break would split "128" across two lines and read as a
   * different number. A value that short cannot overflow anyway, and if one
   * ever does, the geometric check in `adapt_audit.mjs` reports it as overflow
   * — which is the honest signal. A wrap rule there would make a wrong number
   * look intentional.
   */
  it("does not wrap the data rungs, where a break would change the value", () => {
    const blocks = [...CSS.matchAll(/([^{}]+)\{([^}]*overflow-wrap:\s*anywhere[^}]*)\}/g)]
    for (const [, selector] of blocks) {
      expect(selector).not.toMatch(/\.text-data-/)
    }
  })
})

describe("§6.1 touch-target floor", () => {
  /**
   * P6.1 measured all 35 surfaces and found the 44x44 floor implemented
   * nowhere: interactive heights ran 20/24/27/28/32/33/34/38/40px, and the
   * kit's DEFAULT button was 34px. A screenshot cannot show this, which is how
   * it survived five phases of visual review.
   */
  it("declares a 44px floor for real controls", () => {
    const block = CSS.match(/@media\s*\(pointer:\s*coarse\)\s*\{([\s\S]*?)\n\}/)
    expect(block, "no (pointer: coarse) block in index.css").toBeTruthy()
    expect(block![1]).toMatch(/min-block-size:\s*44px/)
    expect(block![1]).toMatch(/\bbutton\b/)
    expect(block![1]).toMatch(/\binput\b/)
    expect(block![1]).toMatch(/\bselect\b/)
    expect(block![1]).toMatch(/\btextarea\b/)
  })

  /**
   * Keyed on the pointer, not on a width. A 375px-wide desktop window is not a
   * finger, and the teacher/admin portals are deliberately DENSITY 7 (§3.3) for
   * a mouse — widening their table controls on a narrow desktop window would be
   * a regression dressed as a fix. Stated as a test because "make it a mobile
   * breakpoint" is the obvious-looking change someone will reach for.
   */
  it("keys the floor on the pointer rather than a width breakpoint", () => {
    const touchRules = [...CSS.matchAll(/@media[^{]*\{[^{]*\{[^}]*min-block-size:\s*44px/g)]
    expect(touchRules.length).toBeGreaterThan(0)
    for (const [rule] of touchRules) {
      expect(rule).toMatch(/pointer:\s*coarse/)
      expect(rule).not.toMatch(/max-width/)
    }
  })

  /**
   * `buttonVariants` renders this recipe onto `<a>` elements (the 404 screen's
   * way out, the landing CTAs), and an anchor is not matched by the global
   * `button` selector. Those anchors measured 32-34px tall on every mobile
   * width, so both renderings of the same control have to state the floor.
   */
  it("carries the floor on the button recipe, which is also used on anchors", () => {
    const button = stripComments(
      readFileSync(join(process.cwd(), "src/components/ui/button.tsx"), "utf8"),
    )
    expect(button).toMatch(/pointer-coarse:min-h-11/)
  })
})

describe("§6.1 no horizontal scroll", () => {
  it("keeps overflow-x: clip on html and body", () => {
    expect(CSS).toMatch(/html,\s*body\s*\{[^}]*overflow-x:\s*clip/)
  })

  /**
   * The regression pin. `overflow-x: clip` makes `documentElement.scrollWidth`
   * permanently equal to `clientWidth`, so ANY check gated on the difference
   * between them is vacuous in this codebase. Measured, not assumed: a 900px
   * div in a 320px viewport reports scrollWidth 900 without the clip rule and
   * scrollWidth 320 with it, while its bounding rect ends at x=900 either way.
   *
   * Both audit scripts must therefore read element geometry. If someone
   * reinstates the cheap guard — and it looks entirely reasonable, which is how
   * it survived four phases — this fails.
   *
   * The first draft of this pin matched `scrollWidth\s*<=?\s*clientWidth`, i.e.
   * the destructured spelling the original happened to use, and was verified by
   * inversion against exactly that. It passed the same guard written
   * `el.scrollWidth > el.clientWidth`: same defect, one property access and one
   * flipped operator away. A pin that only catches a verbatim revert is the
   * phase's own finding one level up — a rule that looks like it covers a case
   * and does not. It now matches either identifier order, any comparison
   * operator, and any receiver, within a single statement.
   */
  const SCROLL_WIDTH_COMPARISON = [
    /\bscrollWidth\b[^;{}\n]{0,80}?[<>]=?[^;{}\n]{0,80}?\bclientWidth\b/,
    /\bclientWidth\b[^;{}\n]{0,80}?[<>]=?[^;{}\n]{0,80}?\bscrollWidth\b/,
  ]

  it("neither audit script gates horizontal overflow on scrollWidth", () => {
    for (const script of ["scripts/audit.mjs", "scripts/adapt_audit.mjs"]) {
      const source = stripComments(readFileSync(join(process.cwd(), script), "utf8"))
      expect(
        SCROLL_WIDTH_COMPARISON.some((re) => re.test(source)),
        `${script} compares scrollWidth to clientWidth; overflow-x: clip makes that comparison always false`,
      ).toBe(false)
      // And it must still be looking: geometry, on every element.
      expect(source).toMatch(/getBoundingClientRect/)
    }
  })
})

describe("§6.1 what the touch gate measures", () => {
  const AUDIT = stripComments(readFileSync(join(process.cwd(), "scripts/adapt_audit.mjs"), "utf8"))

  /**
   * Two controls in this product are deliberately not their own hit target:
   * `FileDrop`'s `sr-only` file input (measured 1x44) and the `appearance-none`
   * checkbox/radio input inside its 18px painted box (measured 16x16). The
   * 44px floor is on the LABEL in both cases, for reasons stated in
   * `index.css` — on the radio it is load-bearing, since a floor on the input
   * would hang an invisible hit area over the next option.
   *
   * So the audit re-points those controls at their label rather than exempting
   * them. The distinction matters: re-pointing still enforces the floor, on the
   * element that carries it, and an input with NO label keeps being measured as
   * itself, because an unlabelled hidden control is a real defect.
   *
   * P6.1 second pass: re-pointing must choose by SIZE, not by document order.
   * `FileDrop` binds two labels to the same input — a 13px caption ("Scanned
   * paper") and the drop zone a finger actually lands on — and the first draft
   * used `querySelector`, which returns whichever comes first in the markup.
   * That was the caption, so a full run reported the product's largest tap
   * target as its smallest, 40 times, on the one flow the whole product exists
   * for. The floor asks whether there is something 44x44 to aim at, so where
   * several labels are bound, the biggest one is the honest answer.
   */
  it("re-points a hidden control at its label instead of dropping it", () => {
    expect(AUDIT).toMatch(/aimedAt/)
    // The fallback is the control itself, never a silent skip.
    expect(AUDIT).toMatch(/aimedAt\(el, cs\)\s*\?\?\s*\{\s*el,\s*rect\s*\}/)
    // No label found means no substitution.
    expect(AUDIT).toMatch(/if \(rects\.length === 0\) return null/)
    // ALL bound labels are considered, not just the first in document order.
    expect(AUDIT).toMatch(/querySelectorAll\(`label\[for=/)
    expect(AUDIT).not.toMatch(/querySelector\(`label\[for=/)
    // And the winner is chosen by area.
    expect(AUDIT).toMatch(/rect\.width \* .*\.rect\.height/)
  })

  /**
   * The floor carries 0.5px of tolerance, and the pin is here so that nobody
   * "tidies" it back to a bare `< 44`.
   *
   * An element whose CSS floor is exactly `min-block-size: 44px` measures
   * 43.95-44.0 depending on the fractional offset it lands on, because Chromium
   * lays out in 1/64px units. Without the tolerance this gate returned a
   * different answer on identical runs — one finding, then two, then a
   * different element — which trains people to re-run until it passes. That is
   * worse than the vacuous check this file replaced, because that one was at
   * least consistently wrong.
   *
   * Both the size rule and the spacing rule must use the same floor: a control
   * that clears the size rule must not still count as "tiny" for spacing.
   */
  it("tolerates sub-pixel layout quantization, on both rules", () => {
    expect(AUDIT).toMatch(/const FLOOR = 44 - 0\.5/)
    expect(AUDIT).toMatch(/width < FLOOR \|\| target\.rect\.height < FLOOR/)
    expect(AUDIT).toMatch(/r\.width < 44 - 0\.5 \|\| r\.height < 44 - 0\.5/)
    // The tolerance must stay sub-pixel. A whole pixel of slack starts letting
    // real misses through, and the genuine one found this phase was 43.7px.
    for (const [, slack] of AUDIT.matchAll(/44 - (\d+(?:\.\d+)?)/g)) {
      expect(Number(slack)).toBeLessThanOrEqual(0.5)
    }
  })

  /**
   * The OTP row cannot meet the floor on the inline axis at 320px: six 44px
   * boxes plus five gaps need 284px and the card offers ~248px. That is a real
   * exemption, so it is REPORTED rather than dropped — a gate that hides its
   * own carve-outs is the vacuous-gate defect above wearing a different hat.
   */
  it("reports call-site exemptions instead of silently passing them", () => {
    expect(AUDIT).toMatch(/data-touch-floor-exempt/)
    expect(AUDIT).toMatch(/exemptTarget/)
    // Exempt findings must not fail the run, and must still be printed.
    expect(AUDIT).toMatch(/EXEMPT_KINDS\.has\(f\.kind\)/)
    expect(AUDIT).toMatch(/exempt \(stated at the call site\)/)
    // The run's pass/fail reads the non-exempt set, never the raw findings.
    expect(AUDIT).toMatch(/if \(failures\.length\) process\.exitCode = 1/)
  })

  /**
   * A waiver stated at the call site has to cover BOTH rules, or it is not a
   * waiver.
   *
   * The OTP row was exempted from the size floor and then failed the SPACING
   * rule 30 times on the same six inputs, because the arithmetic that makes the
   * floor unreachable at 320px (six 44px boxes plus five gaps need 284px in a
   * ~248px card) is the same arithmetic that puts them 4px apart. No edit could
   * clear those findings without undoing the reason for the exemption.
   *
   * Only when BOTH sides share the same waiver, though: one exempt control
   * crowding an ordinary one is still a real mis-tap risk, and the reason
   * written on the OTP row is about the digit boxes among themselves.
   */
  it("honours a call-site waiver on the spacing rule too, but only within it", () => {
    expect(AUDIT).toMatch(/exemptPair/)
    // Both sides, and the SAME waiver element — not merely "either is exempt".
    expect(AUDIT).toMatch(/a\.exempt && b\.exempt && a\.exempt === b\.exempt/)
    // Still reported, never dropped.
    expect(AUDIT).toMatch(/out\.exemptPair\.push/)
    expect(AUDIT).toMatch(/EXEMPT_KINDS = new Set\(\["exemptTarget", "exemptPair"\]\)/)
  })

  /**
   * Every exemption the product takes must name itself. An unattributed
   * `data-touch-floor-exempt` is an exemption nobody can review.
   */
  it("every touch-floor exemption in the product states a reason", () => {
    const src = join(process.cwd(), "src")
    const files: string[] = []
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) walk(full)
        else if (entry.name.endsWith(".tsx")) files.push(full)
      }
    }
    walk(src)

    const taken = files.flatMap((file) =>
      [...readFileSync(file, "utf8").matchAll(/data-touch-floor-exempt(=("[^"]*"|\{[^}]*\}))?/g)].map(
        (m) => ({ file, text: m[0] }),
      ),
    )
    // There is exactly one today; the assertion is on the shape, not the count.
    expect(taken.length).toBeGreaterThan(0)
    for (const { file, text } of taken) {
      expect(text, `${file} takes the touch-floor exemption without a reason`).toMatch(/=/)
      expect(text.replace(/^[^=]*=/, "").replace(/["{}]/g, "").trim().length).toBeGreaterThan(2)
    }
  })
})

/*
 * P6.5. The gate could not reach the pages it was measuring.
 *
 * `adapt_audit.mjs` opens by saying it walks "the SAME registry that harness
 * does — imported, never restated". The registry was imported. The **port** was
 * restated: the audit served `dist/` on 4321, and six of the `act` callbacks it
 * imports from `capture_surface.mjs` navigate by absolute URL to 4319, because
 * they assert on routing itself ("/ renders the landing page for a signed-out
 * visitor") and an absolute URL needs a host.
 *
 * The run therefore died at the `landing` surface, eighth of thirty-five, with
 * `ERR_CONNECTION_REFUSED`, and the twenty-seven surfaces after it were never
 * measured at any width. The one way it does not die is if something else
 * happens to be listening on 4319 — a leftover capture server, say — in which
 * case a stranger's build silently answers a question about ours. That is
 * BLOCKERS.md B4 ("the e2e suite silently runs against whatever is already on
 * port 8000") in the gate written after it.
 *
 * D6.7's question, for the fourth file this phase has asked it of: what
 * re-states a value, and what checks that the two still agree? Here the answer
 * is that the restatement is gone, and this is what keeps it gone.
 */
describe("§6.1 the gate and the registry agree on where the server is", () => {
  const AUDIT = readFileSync(join(process.cwd(), "scripts/adapt_audit.mjs"), "utf8")
  const CAPTURE = readFileSync(join(process.cwd(), "scripts/capture_surface.mjs"), "utf8")

  it("declares the port in exactly one place", () => {
    expect(stripComments(CAPTURE)).toMatch(/export const PORT = \d+/)
    expect(stripComments(AUDIT)).not.toMatch(/const PORT\s*=/)
    expect(stripComments(AUDIT)).not.toMatch(/const BASE\s*=/)
  })

  it("imports both from the registry it already imports the surfaces from", () => {
    expect(stripComments(AUDIT)).toMatch(
      /import \{[^}]*\bBASE\b[^}]*\bPORT\b[^}]*\} from "\.\/capture_surface\.mjs"/s,
    )
  })

  /*
   * The other half, and the one that matters when the port is busy rather than
   * mismatched. With `--strictPort` our server exits instead of picking another
   * port, and the wait loop's `fetch` would then be answered by whatever is
   * already there. Checking the child's exit status before believing the fetch
   * is what makes that case a named failure rather than a green run about
   * somebody else's `dist/`.
   */
  it("refuses to measure a server it did not start", () => {
    expect(AUDIT).toMatch(/server\.exitCode !== null/)
    expect(AUDIT).toMatch(/will NOT/)
  })

  /*
   * And the reason the mismatch took a throwaway script to diagnose: both of
   * the server's pipes were opened and never read, so vite's own
   * "Port 4319 is already in use" went to a buffer nobody emptied. A gate that
   * discards the evidence of its own failure makes every failure look like a
   * flake.
   */
  it("keeps the server's own output for when it dies", () => {
    expect(AUDIT).toMatch(/child\.stderr\.on\("data"/)
    expect(AUDIT).toMatch(/child\.stdout\.on\("data"/)
  })
})
