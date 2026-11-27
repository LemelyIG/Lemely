/*
 * A just-enough in-memory DOM, so REAL React (`react-dom/client`) can mount a
 * component under this suite's plain-Node environment and run its effects.
 *
 * Why this exists. `renderToStaticMarkup` never runs `useEffect`, so a bug that
 * lives in an effect's dependency list (focus jumping on every step) is
 * invisible to it. D3.20 keeps jsdom and @testing-library out of this repo on
 * purpose, and this does not reopen that: no dependency is added, and nothing
 * here models a browser. It implements only what React's reconciler and its
 * event system call on the host: tree edits, attributes, listeners with
 * capture/bubble propagation, and a focus model with `document.activeElement`
 * (focus moves only to a connected, focusable element, and falls back to the
 * body when the focused element is removed).
 *
 * Install it BEFORE `react-dom/client` is first imported: React decides
 * whether a DOM exists when that module loads.
 */
import type { ReactElement } from "react"

type Handler = (event: FakeEvent) => void
interface Listener {
  fn: Handler
  capture: boolean
}

const ELEMENT = 1
const TEXT = 3
const DOCUMENT = 9
const HTML_NS = "http://www.w3.org/1999/xhtml"

export class FakeEvent {
  target: FakeNode | null = null
  currentTarget: FakeNode | null = null
  defaultPrevented = false
  eventPhase = 0
  isTrusted = false
  timeStamp = Date.now()
  stopped = false
  readonly type: string
  readonly bubbles: boolean
  readonly cancelable: boolean
  constructor(type: string, bubbles = true, cancelable = true) {
    this.type = type
    this.bubbles = bubbles
    this.cancelable = cancelable
  }
  stopPropagation() {
    this.stopped = true
  }
  stopImmediatePropagation() {
    this.stopped = true
  }
  preventDefault() {
    this.defaultPrevented = true
  }
}

export class FakeNode {
  parentNode: FakeNode | null = null
  childNodes: FakeNode[] = []
  attrs = new Map<string, string>()
  style: Record<string, unknown> & { setProperty: (name: string, value: string) => void } = { setProperty() {} }
  private listeners = new Map<string, Listener[]>()
  private text = ""
  readonly nodeType: number
  readonly nodeName: string
  ownerDocument: FakeDocument
  readonly namespaceURI: string | null
  constructor(nodeType: number, nodeName: string, ownerDocument: FakeDocument, namespaceURI: string | null = HTML_NS) {
    this.nodeType = nodeType
    this.nodeName = nodeName
    this.ownerDocument = ownerDocument
    this.namespaceURI = namespaceURI
  }

  get tagName() {
    return this.nodeName
  }
  get firstChild() {
    return this.childNodes[0] ?? null
  }
  get lastChild() {
    return this.childNodes[this.childNodes.length - 1] ?? null
  }
  get nextSibling(): FakeNode | null {
    const siblings = this.parentNode?.childNodes
    return siblings ? (siblings[siblings.indexOf(this) + 1] ?? null) : null
  }
  get previousSibling(): FakeNode | null {
    const siblings = this.parentNode?.childNodes
    return siblings ? (siblings[siblings.indexOf(this) - 1] ?? null) : null
  }
  get isConnected(): boolean {
    return chain(this).includes(this.ownerDocument)
  }

  get nodeValue() {
    return this.nodeType === TEXT ? this.text : null
  }
  set nodeValue(value: string | null) {
    this.text = String(value ?? "")
  }
  get textContent(): string {
    if (this.nodeType === TEXT) return this.text
    return this.childNodes.map((c) => c.textContent).join("")
  }
  set textContent(value: string) {
    for (const c of [...this.childNodes]) this.removeChild(c)
    if (value) this.appendChild(this.ownerDocument.createTextNode(value))
  }

  appendChild(child: FakeNode) {
    return this.insertBefore(child, null)
  }
  insertBefore(child: FakeNode, before: FakeNode | null) {
    child.parentNode?.removeChild(child)
    child.parentNode = this
    const at = before ? this.childNodes.indexOf(before) : -1
    if (at < 0) this.childNodes.push(child)
    else this.childNodes.splice(at, 0, child)
    return child
  }
  removeChild(child: FakeNode) {
    const at = this.childNodes.indexOf(child)
    if (at < 0) throw new Error("removeChild: not a child")
    this.childNodes.splice(at, 1)
    child.parentNode = null
    // A browser drops focus to the body when the focused element leaves the page.
    const active = this.ownerDocument.activeElement
    if (active && child.contains(active)) this.ownerDocument.activeElement = null
    return child
  }
  contains(other: FakeNode | null): boolean {
    for (let n = other; n; n = n.parentNode) if (n === this) return true
    return false
  }

  setAttribute(name: string, value: unknown) {
    this.attrs.set(name, String(value))
  }
  setAttributeNS(_ns: string | null, name: string, value: unknown) {
    this.attrs.set(name, String(value))
  }
  getAttribute(name: string) {
    return this.attrs.get(name) ?? null
  }
  hasAttribute(name: string) {
    return this.attrs.has(name)
  }
  removeAttribute(name: string) {
    this.attrs.delete(name)
  }
  removeAttributeNS(_ns: string | null, name: string) {
    this.attrs.delete(name)
  }

  addEventListener(type: string, fn: Handler, options?: boolean | { capture?: boolean }) {
    const capture = typeof options === "boolean" ? options : Boolean(options?.capture)
    const list = this.listeners.get(type) ?? []
    list.push({ fn, capture })
    this.listeners.set(type, list)
  }
  removeEventListener(type: string, fn: Handler, options?: boolean | { capture?: boolean }) {
    const capture = typeof options === "boolean" ? options : Boolean(options?.capture)
    const list = this.listeners.get(type)
    if (!list) return
    this.listeners.set(type, list.filter((l) => !(l.fn === fn && l.capture === capture)))
  }

  /** Capture from the root down to the target, then bubble back up if the event bubbles. */
  dispatchEvent(event: FakeEvent) {
    const path = chain(this)
    event.target = this
    const fire = (node: FakeNode, capture: boolean) => {
      if (event.stopped) return
      event.currentTarget = node
      for (const l of [...(node.listeners.get(event.type) ?? [])]) if (l.capture === capture) l.fn(event)
    }
    for (let i = path.length - 1; i >= 0; i--) fire(path[i], true)
    fire(this, false)
    if (event.bubbles) for (let i = 1; i < path.length; i++) fire(path[i], false)
    event.currentTarget = null
    return !event.defaultPrevented
  }

  focus() {
    if (!this.isConnected || !isFocusable(this)) return
    this.ownerDocument.activeElement = this
  }
  blur() {
    if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = null
  }
}

/** The node and each of its ancestors, nearest first. */
function chain(node: FakeNode): FakeNode[] {
  const out: FakeNode[] = []
  for (let n: FakeNode | null = node; n; n = n.parentNode) out.push(n)
  return out
}

function isFocusable(node: FakeNode): boolean {
  if (node.nodeType !== ELEMENT || node.attrs.has("disabled")) return false
  const tag = node.nodeName.toLowerCase()
  if (tag === "button" || tag === "input" || tag === "select" || tag === "textarea") return true
  if (tag === "a" && node.attrs.has("href")) return true
  return node.attrs.has("tabindex")
}

export class FakeDocument extends FakeNode {
  readonly documentElement: FakeNode
  readonly body: FakeNode
  readonly defaultView: Record<string, unknown>
  private focused: FakeNode | null = null
  constructor() {
    super(DOCUMENT, "#document", null as unknown as FakeDocument, null)
    this.ownerDocument = this
    this.documentElement = this.createElement("html")
    this.body = this.createElement("body")
    this.appendChild(this.documentElement)
    this.documentElement.appendChild(this.body)
    this.defaultView = {}
  }
  get activeElement(): FakeNode {
    return this.focused ?? this.body
  }
  set activeElement(node: FakeNode | null) {
    this.focused = node
  }
  createElement(tag: string) {
    return new FakeNode(ELEMENT, tag.toUpperCase(), this)
  }
  createElementNS(ns: string, tag: string) {
    return new FakeNode(ELEMENT, ns === HTML_NS ? tag.toUpperCase() : tag, this, ns)
  }
  createTextNode(text: string) {
    const node = new FakeNode(TEXT, "#text", this)
    node.nodeValue = text
    return node
  }
}

export interface FakeDom {
  document: FakeDocument
  restore: () => void
}

const GLOBALS = ["window", "document", "HTMLElement", "HTMLIFrameElement", "Node", "navigator"] as const

/** Puts a fresh fake document on `globalThis`. Call `restore()` when the file is done. */
export function installFakeDom(): FakeDom {
  const document = new FakeDocument()
  class HTMLIFrameElement {}
  const view = document.defaultView
  Object.assign(view, {
    document,
    HTMLIFrameElement,
    HTMLElement: FakeNode,
    Node: FakeNode,
    addEventListener() {},
    removeEventListener() {},
    getComputedStyle: () => ({ getPropertyValue: () => "", paddingBottom: "0px" }),
  })
  view.window = view
  view.self = view
  view.top = view
  const g = globalThis as Record<string, unknown>
  const previous = new Map<string, PropertyDescriptor | undefined>()
  for (const name of GLOBALS) previous.set(name, Object.getOwnPropertyDescriptor(globalThis, name))
  const set = (name: string, value: unknown) => Object.defineProperty(globalThis, name, { value, configurable: true, writable: true })
  set("window", view)
  set("document", document)
  set("HTMLElement", FakeNode)
  set("HTMLIFrameElement", HTMLIFrameElement)
  set("Node", FakeNode)
  if (!g.navigator) set("navigator", { userAgent: "fake-dom" })
  set("IS_REACT_ACT_ENVIRONMENT", true)
  return {
    document,
    restore() {
      for (const [name, descriptor] of previous) {
        if (descriptor) Object.defineProperty(globalThis, name, descriptor)
        else delete g[name]
      }
      delete g.IS_REACT_ACT_ENVIRONMENT
    },
  }
}

export interface Mounted {
  container: FakeNode
  /** Re-render the root with a new element, inside `act`. */
  render: (element: ReactElement) => Promise<void>
  unmount: () => Promise<void>
}

/** Mounts `element` into a connected container with the real React DOM renderer. */
export async function mount(dom: FakeDom, element: ReactElement): Promise<Mounted> {
  const { createRoot } = await import("react-dom/client")
  const { act } = await import("react")
  const container = dom.document.createElement("div")
  dom.document.body.appendChild(container)
  const root = createRoot(container as unknown as Element)
  const render = async (next: ReactElement) => {
    await act(async () => root.render(next))
  }
  await render(element)
  return {
    container,
    render,
    unmount: async () => {
      await act(async () => root.unmount())
    },
  }
}

/** Dispatches a bubbling click through React's real delegated handlers, inside `act`. */
export async function click(node: FakeNode) {
  const { act } = await import("react")
  await act(async () => {
    node.dispatchEvent(new FakeEvent("click"))
  })
}

/** Dispatches a non-bubbling event (an image `error`, say) at the node, inside `act`. */
export async function fire(node: FakeNode, type: string) {
  const { act } = await import("react")
  await act(async () => {
    node.dispatchEvent(new FakeEvent(type, false))
  })
}

export function findAll(root: FakeNode, test: (node: FakeNode) => boolean): FakeNode[] {
  const out: FakeNode[] = []
  const walk = (node: FakeNode) => {
    if (node.nodeType === ELEMENT && test(node)) out.push(node)
    node.childNodes.forEach(walk)
  }
  walk(root)
  return out
}

export function find(root: FakeNode, test: (node: FakeNode) => boolean): FakeNode | null {
  return findAll(root, test)[0] ?? null
}

export const byLabel = (label: string) => (node: FakeNode) => node.getAttribute("aria-label") === label
export const byTag = (tag: string) => (node: FakeNode) => node.nodeName.toLowerCase() === tag
export const byText = (tag: string, text: string) => (node: FakeNode) => node.nodeName.toLowerCase() === tag && node.textContent.trim() === text
