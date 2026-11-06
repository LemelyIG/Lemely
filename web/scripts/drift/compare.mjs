/*
 * Pixel comparison for the drift gate (home-drift.mjs).
 *
 * A "differing pixel" is what pixelmatch reports at threshold 0.1 (its YIQ
 * colour-distance default), with anti-aliased pixels excluded (its default).
 * That is the gate's definition of a pixel that differs; the spec's "0
 * differing pixels" means 0 under this definition.
 *
 * Two captures of different sizes are padded to the larger size with opaque
 * magenta, so every row or column one side lacks counts as differing.
 */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { PNG } from "pngjs"
import pixelmatch from "pixelmatch"

export const MAX_PCT = 15
const HERE = path.dirname(fileURLToPath(import.meta.url))
const JUSTIFICATIONS_PATH = path.join(HERE, "justifications.json")

function padTo(png, width, height) {
  if (png.width === width && png.height === height) return png
  const out = new PNG({ width, height })
  for (let i = 0; i < out.data.length; i += 4) {
    out.data[i] = 255
    out.data[i + 1] = 0
    out.data[i + 2] = 255
    out.data[i + 3] = 255
  }
  PNG.bitblt(png, out, 0, 0, png.width, png.height, 0, 0)
  return out
}

/** Diff two PNG buffers, write the diff image, return the counts. */
export function diffPngs(aBuffer, bBuffer, diffPath) {
  const a = PNG.sync.read(aBuffer)
  const b = PNG.sync.read(bBuffer)
  const width = Math.max(a.width, b.width)
  const height = Math.max(a.height, b.height)
  const pa = padTo(a, width, height)
  const pb = padTo(b, width, height)
  const out = new PNG({ width, height })
  const diff = pixelmatch(pa.data, pb.data, out.data, width, height, { threshold: 0.1 })
  fs.mkdirSync(path.dirname(diffPath), { recursive: true })
  fs.writeFileSync(diffPath, PNG.sync.write(out))
  const total = width * height
  return {
    diff,
    total,
    pct: total === 0 ? 0 : (diff / total) * 100,
    sizes: { a: [a.width, a.height], b: [b.width, b.height] },
  }
}

/** Most specific justification for a scene key `${id}@${window}@${theme}`:
 * exact key, then `${id}@${window}`, then `${id}@*@${theme}`, then `${id}`. */
export function findJustification(key, table = readJustifications()) {
  const [id, win, theme] = key.split("@")
  for (const candidate of [key, `${id}@${win}`, `${id}@*@${theme}`, id]) {
    if (table[candidate]) return { key: candidate, ...table[candidate] }
  }
  return null
}

export function readJustifications() {
  return JSON.parse(fs.readFileSync(JUSTIFICATIONS_PATH, "utf8"))
}

/**
 * "pass": 0 differing pixels.
 * "pass-justified": differs, has a written justification whose `approved` is
 *   "yes", and (rule "gate") is at most 15%. Rule "log" has no 15% cap.
 * "fail": anything else: no justification, justification not yet approved
 *   (approval pending), or a gate scene over 15% even when justified.
 */
export function judge(result, justification, rule = "gate") {
  if (result.diff === 0) return { outcome: "pass", reason: "no differing pixels" }
  if (rule === "gate" && result.pct > MAX_PCT) {
    return { outcome: "fail", reason: `${result.pct.toFixed(2)}% differs, over the ${MAX_PCT}% gate cap` }
  }
  const written = Boolean(justification && justification.justification && justification.justification.trim())
  if (!written) return { outcome: "fail", reason: "differs with no written justification" }
  const approved = String(justification.approved ?? "").trim().toLowerCase() === "yes"
  if (!approved) return { outcome: "fail", reason: "justified but approval is pending (approved must be \"yes\")" }
  return { outcome: "pass-justified", reason: "justified and approved" }
}

export function verdict(result, justification, rule = "gate") {
  return judge(result, justification, rule).outcome
}

/**
 * Process exit code for a set of rows: 0 only when at least one row was actually
 * compared (pass or pass-justified) and none failed. "captured" rows (never
 * diffed, need human review) neither pass nor fail, but a run holding only
 * captured rows compared nothing and exits 1.
 */
export function exitCodeFor(rows) {
  const compared = rows.some((r) => r.outcome === "pass" || r.outcome === "pass-justified")
  return compared && rows.every((r) => r.outcome !== "fail") ? 0 : 1
}
