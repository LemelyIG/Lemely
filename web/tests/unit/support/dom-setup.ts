/*
 * Opt-in DOM setup for component tests. Import it for its side effects, as the
 * first import of a `// @vitest-environment jsdom` test file:
 *
 *   // @vitest-environment jsdom
 *   import "./support/dom-setup"
 *
 * It is deliberately NOT a vitest `setupFiles` entry, so the node-only default
 * (D3.20) is untouched and no existing test pays for it.
 */
import { afterEach } from "vitest"
import { cleanup } from "@testing-library/react"

// React reads this flag to know that state updates outside `act` are expected
// in a test runner; Testing Library sets it for jest/vitest globals only.
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

if (typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })
}

if (typeof globalThis.ResizeObserver !== "function") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

// jsdom logs "not implemented" for scrollTo (scrollLock calls it).
window.scrollTo = () => {}

// Unmount between tests so portals do not leak.
afterEach(() => cleanup())
