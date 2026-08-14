/*
 * "Do not measure a server you did not start" — the precondition, not the
 * afterthought (P7.1).
 *
 * ── The bug this exists to close, and why it took three attempts ───────────
 *
 * BLOCKERS.md B4: the e2e suite silently ran against whatever already held its
 * port, because `reuseExistingServer` told Playwright to adopt it. The lesson
 * was recorded and the same defect then appeared twice more inside the gates
 * written after it:
 *
 * 1. **D6.10** — `adapt_audit.mjs` served `dist/` on 4321 while six `act`
 *    callbacks it imports navigated to 4319, so it only ever completed when
 *    something *else* was holding 4319 for it. Fixed by importing the port
 *    instead of restating it, and by adding a guard that reads the spawned
 *    server's exit code before each fetch.
 * 2. **P7.1** — that guard cannot fire. With a foreign server on the port and
 *    `--strictPort`, the imposter answers a `fetch` at **+164ms** while our own
 *    vite needs **+577ms** to fail its bind and exit 1. The poll checks the exit
 *    code first, finds `null`, fetches, is answered by the squatter, and
 *    returns success. Measured on this machine, twice, rather than reasoned
 *    about. It was found by a Phase 7 sweep quietly adopting a `vite preview`
 *    that had been orphaned on 4319 for an hour and forty minutes.
 *
 * **A guard placed after the spawn cannot win this race**, because a server
 * that is already up will always answer faster than an honest one can discover
 * it has lost. So the check moves before the spawn, where the question is not
 * "who answered?" but "is anyone there?" — and that one has no race in it.
 *
 * It lives in its own module because `adapt_audit.mjs`, `audit.mjs`,
 * `capture_surface.mjs` and `gallery.mjs` each spawn their own preview server,
 * and four copies of a rule is how one of them keeps the old version. That is
 * the same failure this phase found in `stripComments`, which had four
 * divergent copies across six gates.
 */

/**
 * Throw unless nothing is listening on `base`.
 *
 * `label` names the caller in the message, so a developer who hits this knows
 * which of the four harnesses refused and why.
 */
export async function assertPortFree(base, port, label = "this run") {
  try {
    const res = await fetch(base, { signal: AbortSignal.timeout(1500) })
    throw new Error(
      `port ${port} is already answering (HTTP ${res.status}). ${label} will NOT ` +
        `measure a server it did not start, and cannot know what that one is serving ` +
        `— it may be a build from another branch, or another checkout entirely. ` +
        `Stop it and re-run:\n  pkill -f "vite preview --port ${port}"`,
    )
  } catch (error) {
    /*
     * The healthy path is a refused connection, which `fetch` reports as a
     * TypeError wrapping ECONNREFUSED. Everything else — including the throw
     * above, and a timeout against something that accepted the socket and then
     * said nothing — is a real condition and must propagate. Re-throwing our
     * own error here is deliberate: swallowing it would turn this guard into
     * the vacuous kind it was written to replace.
     */
    const refused =
      error instanceof TypeError ||
      /ECONNREFUSED|fetch failed|Failed to fetch|other side closed/i.test(
        String(error?.message ?? error),
      )
    if (!refused) throw error
  }
}
