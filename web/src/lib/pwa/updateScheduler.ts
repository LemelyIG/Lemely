/*
 * Packet A7. Split out of `useServiceWorkerUpdate.ts` for one reason: that
 * file imports `virtual:pwa-register/react`, a module the VitePWA plugin
 * injects at build time and `vitest.config.ts` never loads (deliberately —
 * see that config's own docstring on why the test runner is not an
 * extension of `vite.config.ts`). Importing anything from a file that pulls
 * in a virtual module fails module resolution outright under vitest, not
 * just at the call site — so the one piece of this feature that is
 * genuinely pure has to live somewhere the hook can import from, not the
 * other way around.
 */

/** How often to poll for an update in the background, so a tab left open for
 * hours still notices a release — on top of the check that also runs every
 * time the tab regains visibility. */
export const UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000

/** The slice of `document`/`window` `scheduleUpdateChecks` needs, so a test
 * can inject fakes without a real DOM (D3.20 — no jsdom in this repo). */
export interface UpdateSchedulerEnv {
  /** Returns an unsubscribe function, mirroring `removeEventListener`. */
  addVisibilityListener: (onVisible: () => void) => () => void
  setInterval: (callback: () => void, ms: number) => number
  clearInterval: (id: number) => void
}

export function realUpdateSchedulerEnv(): UpdateSchedulerEnv {
  return {
    addVisibilityListener: (onVisible) => {
      const handler = () => {
        if (document.visibilityState === "visible") onVisible()
      }
      document.addEventListener("visibilitychange", handler)
      return () => document.removeEventListener("visibilitychange", handler)
    },
    setInterval: (callback, ms) => window.setInterval(callback, ms),
    clearInterval: (id) => window.clearInterval(id),
  }
}

/**
 * Wires periodic `registration.update()` polling — once whenever the tab
 * regains visibility, and once every `UPDATE_CHECK_INTERVAL_MS` regardless —
 * so a build that shipped while this tab sat in the background is still
 * noticed. Returns the cleanup function.
 */
export function scheduleUpdateChecks(
  registration: Pick<ServiceWorkerRegistration, "update">,
  env: UpdateSchedulerEnv = realUpdateSchedulerEnv(),
): () => void {
  const checkForUpdate = () => {
    registration.update().catch(() => {
      // A failed check is not worth surfacing; the next poll tries again.
    })
  }

  const removeVisibilityListener = env.addVisibilityListener(checkForUpdate)
  const intervalId = env.setInterval(checkForUpdate, UPDATE_CHECK_INTERVAL_MS)

  return () => {
    removeVisibilityListener()
    env.clearInterval(intervalId)
  }
}
