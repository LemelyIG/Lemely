import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { afterEach, describe, expect, it } from "vitest"
import {
  SNAPSHOT_LIMIT,
  SNAPSHOT_NODE_CAP,
  captureColumn,
  copyElement,
  createSnapshotStore,
  navigateSnapshotAction,
  watchSessionForSnapshots,
  type SessionLike,
} from "@/lib/nav/pageSnapshot"

describe("snapshot store", () => {
  it("keeps the most recently used entries within the limit", () => {
    const store = createSnapshotStore<string>(3)
    store.set(1, "a")
    store.set(2, "b")
    store.set(3, "c")
    store.get(1)
    store.set(4, "d")
    expect(store.keys().sort()).toEqual([1, 3, 4])
  })
  it("defaults to five entries", () => {
    const store = createSnapshotStore<number>()
    for (let i = 0; i < 9; i++) store.set(i, i)
    expect(store.keys()).toHaveLength(SNAPSHOT_LIMIT)
    expect(SNAPSHOT_LIMIT).toBe(5)
  })
  it("a push drops the entry at its index and everything beyond", () => {
    const store = createSnapshotStore<string>()
    for (const i of [1, 2, 3, 4]) store.set(i, String(i))
    store.dropFrom(3)
    expect(store.keys().sort()).toEqual([1, 2])
    store.delete(1)
    expect(store.get(1)).toBeUndefined()
  })
})

/** The smallest element the copy touches: tag, attributes, children, text. */
class FakeEl {
  nodeType = 1
  parent: FakeEl | null = null
  children: FakeEl[] = []
  className = ""
  width = 0
  height = 0
  localName: string
  attrs: Record<string, string>
  constructor(localName: string, attrs: Record<string, string> = {}, text?: string) {
    this.localName = localName
    this.attrs = attrs
    if (text !== undefined) this.children.push(new FakeText(text) as unknown as FakeEl)
  }
  get childNodes() {
    return this.children
  }
  cloneNode() {
    return new FakeEl(this.localName, { ...this.attrs })
  }
  removeAttribute(name: string) {
    delete this.attrs[name]
  }
  setAttribute(name: string, value: string) {
    this.attrs[name] = value
  }
  getAttribute(name: string) {
    return this.attrs[name] ?? null
  }
  appendChild(child: FakeEl) {
    this.children.push(child)
    return child
  }
  toDataURL() {
    return "data:image/png;base64,AAAA"
  }
}
class FakeText {
  nodeType = 3
  data: string
  constructor(data: string) {
    this.data = data
  }
  cloneNode() {
    return new FakeText(this.data)
  }
}
const tree = (el: FakeEl, kids: FakeEl[] = []) => {
  kids.forEach((k) => el.children.push(k))
  return el as unknown as Element
}
const state = () => ({ count: 0, cap: SNAPSHOT_NODE_CAP })

describe("copyElement", () => {
  afterEach(() => {
    delete (globalThis as { document?: unknown }).document
  })
  it("strips id, name, tabindex, autofocus and the column marker from every element", () => {
    const root = tree(new FakeEl("div", { "data-shell-column": "", id: "root", class: "x" }), [
      new FakeEl("input", { name: "grade", type: "radio", tabindex: "0", autofocus: "", id: "a" }),
      tree(new FakeEl("section", { id: "s" }), [new FakeEl("a", { href: "/x", tabindex: "0" })]) as unknown as FakeEl,
    ])
    const copy = copyElement(root, state())! as unknown as FakeEl
    const all = (e: FakeEl): FakeEl[] => [e, ...e.children.filter((c) => c.nodeType === 1).flatMap(all)]
    for (const el of all(copy)) {
      for (const attr of ["id", "name", "tabindex", "autofocus", "data-shell-column"]) expect(el.attrs[attr], `${el.localName} ${attr}`).toBeUndefined()
    }
    expect(copy.attrs.class).toBe("x")
    expect(all(copy)[2]?.attrs.href ?? all(copy)[3]?.attrs.href).toBe("/x")
  })
  it("drops live media and scripts", () => {
    const root = tree(new FakeEl("div"), ["video", "audio", "iframe", "embed", "object", "script"].map((t) => new FakeEl(t)).concat(new FakeEl("p", {}, "kept")))
    const copy = copyElement(root, state())! as unknown as FakeEl
    expect(copy.children.map((c) => c.localName)).toEqual(["p"])
  })
  it("turns a small canvas into an image of its pixels, keeping class and style", () => {
    const made: FakeEl[] = []
    ;(globalThis as { document?: unknown }).document = {
      createElement: (tag: string) => {
        const el = new FakeEl(tag)
        made.push(el)
        return el
      },
    }
    const canvas = new FakeEl("canvas", { style: "width:10px" })
    canvas.width = 100
    canvas.height = 50
    canvas.className = "chart"
    const copy = copyElement(canvas as unknown as Element, state())! as unknown as FakeEl & { src: string }
    expect(copy.localName).toBe("img")
    expect(copy.src).toBe("data:image/png;base64,AAAA")
    expect(copy.className).toBe("chart")
    expect(copy.attrs.style).toBe("width:10px")
  })
  it("leaves a canvas over the pixel cap as a blank clone", () => {
    const canvas = new FakeEl("canvas")
    canvas.width = 2000
    canvas.height = 2000
    expect(copyElement(canvas as unknown as Element, state())!.localName).toBe("canvas")
  })
  it("stops at the cap instead of copying the rest", () => {
    const kids = Array.from({ length: 10 }, () => new FakeEl("p"))
    const root = tree(new FakeEl("div"), kids)
    expect(captureColumn(root as unknown as HTMLElement, 0, 5)).toBeNull()
    expect(captureColumn(root as unknown as HTMLElement, 0, 11)).not.toBeNull()
  })
  it("marks the capture inert and hidden from assistive technology, with its scroll", () => {
    const snap = captureColumn(tree(new FakeEl("div")) as unknown as HTMLElement, 240)!
    const attrs = (snap.node as unknown as FakeEl).attrs
    expect(attrs["aria-hidden"]).toBe("true")
    expect(attrs.inert).toBe("")
    expect(snap.scrollY).toBe(240)
  })
})

describe("snapshots never outlive the session", () => {
  function harness(initial: string | null) {
    let listener: (s: SessionLike | null) => void = () => {}
    const store = createSnapshotStore<string>()
    store.set(1, "page")
    watchSessionForSnapshots(
      (l: (s: SessionLike | null) => void) => {
        listener = l
        return () => {}
      },
      store,
      initial,
    )
    return { store, emit: (s: SessionLike | null) => listener(s) }
  }
  it("sign-out clears the store", () => {
    const h = harness("u1")
    h.emit(null)
    expect(h.store.keys()).toEqual([])
  })
  it("a different user clears the store", () => {
    const h = harness("u1")
    h.emit({ userId: "u2" })
    expect(h.store.keys()).toEqual([])
  })
  it("a silent token refresh for the same user keeps it", () => {
    const h = harness("u1")
    h.emit({ userId: "u1" })
    expect(h.store.keys()).toEqual([1])
  })
})

describe("wiring", () => {
  it("App.tsx registers the snapshot capture as navigate middleware", () => {
    const app = src("App.tsx")
    expect(app).toContain("installNavigateMiddleware(router, [snapshotCaptureMiddleware])")
  })
  const src = (p: string) => readFileSync(resolve(__dirname, "../../src", p), "utf8")
  it("the root outlet installs the navigate capture and the session guard, and keeps no timer or click listener", () => {
    const outlet = src("components/root-outlet.tsx")
    expect(outlet).toContain("installSnapshotSessionGuard()")
    expect(outlet).not.toMatch(/setTimeout|addEventListener\("click"/)
  })
})

describe("navigate wrapper decision", () => {
  it("clones on a push, drops the index's copy on a replace, ignores a delta", () => {
    expect(navigateSnapshotAction("/x")).toBe("capture")
    expect(navigateSnapshotAction("/x", { replace: false })).toBe("capture")
    expect(navigateSnapshotAction("/x", { replace: true })).toBe("drop")
    expect(navigateSnapshotAction(-1)).toBe("none")
  })
})
