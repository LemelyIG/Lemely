/*
 * The widget half of `sw.ts` — the Windows 11 / Android widget surface
 * (`vite/manifest.ts`'s `widgets` member, tag `lemely-streak`), backed by
 * `GET /api/student/widget` (packet A5's backend, `lemely/web/routers/widget.py`).
 *
 * Same problem, same fix, as the push handshake `sw.ts` already has
 * (D5.15 §2): a `ServiceWorkerGlobalScope` cannot read `localStorage`, where
 * the bearer token lives, so it cannot make the authenticated
 * `GET /api/student/widget` request itself. It asks an open page instead —
 * the page-side half is `lib/widget/widgetClientBridge.ts` — and falls back
 * to the static `public/widgets/streak-data.json` stub when nothing answers
 * in time.
 *
 * Deliberately typed without `self` or any real `Client`/`Clients` type: only
 * `ClientLike`/`ClientsLike`, narrowed to exactly what this file reads — the
 * same reasoning `sw/shareTarget.ts`'s `ShareTargetFetchEvent` gives for not
 * using the real `FetchEvent`. `MessageChannel` is a genuine Node global (has
 * been since Node 15), so this file, `caches`-free and `self`-free, compiles
 * under `tsconfig.sw.json` (WebWorker) and `tsconfig.app.json` (DOM) alike
 * and is directly exercisable under this suite's plain-Node vitest
 * environment (no jsdom, D3.20) — not just pinned as a source-text gate on
 * `sw.ts`'s wiring.
 *
 * **Known limitation, stated plainly rather than hidden**: since only an open
 * page can supply live data, the widget is only ever as fresh as the last
 * time a tab was open long enough to answer this request. A widget rendered
 * while the app is fully closed — right after the reader adds it to their
 * Widgets Board, or after the device has sat idle for a while — shows
 * whatever the stub says (currently a static "0-day streak, nothing
 * scheduled") until a tab is next opened and `sw.ts`'s `widgetresume` or
 * `activate` handler re-renders it with real numbers.
 */

/** The message a worker sends to a page to ask for the caller's widget data. */
export const WIDGET_DATA_REQUEST = "lemely:widget-data-request"

/** The message a page sends back. */
export const WIDGET_DATA_REPLY = "lemely:widget-data-reply"

/**
 * `GET /api/student/widget`'s reply shape — mirrors
 * `lemely/web/schemas_widget.py`'s `StudentWidgetDTO`/`WidgetNextSessionDTO`
 * field for field, and `public/widgets/streak.json`'s own `${streak}` /
 * `${nextSession.title}` / `${nextSession.startsAt}` template bindings.
 */
export interface WidgetNextSession {
  title: string
  startsAt: string
}

export interface StudentWidgetData {
  streak: number
  nextSession: WidgetNextSession | null
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function isValidNextSession(value: unknown): value is WidgetNextSession {
  if (!isPlainObject(value)) return false
  return (
    typeof value.title === "string" &&
    value.title.trim() !== "" &&
    typeof value.startsAt === "string" &&
    value.startsAt.trim() !== ""
  )
}

/**
 * Turn whatever a page replied with into widget data, or null.
 *
 * A reply arrives over a message channel, so — same rule
 * `pushDecision.ts`'s own header states for the push half — it is untrusted
 * input, validated by shape rather than destructured on faith. Unlike
 * `decidePushNotification`, there is no in-process fallback value to return
 * here: `null` means "the caller should fall back to the static stub",
 * which only `fetchWidgetDataOrStub` (with `fetch` access to
 * `public/widgets/streak-data.json`) can do.
 */
export function decideWidgetData(reply: unknown): StudentWidgetData | null {
  if (!isPlainObject(reply)) return null
  const streak = reply.streak
  if (typeof streak !== "number" || !Number.isFinite(streak) || streak < 0) return null
  const nextSession = reply.nextSession
  if (nextSession === null) return { streak, nextSession: null }
  if (!isValidNextSession(nextSession)) return null
  return { streak, nextSession }
}

/** The narrow slice of a `Client` this handshake needs. */
export interface ClientLike {
  postMessage(message: unknown, transfer: Transferable[]): void
}

/** The narrow slice of `self.clients` this handshake needs. `readonly` on the
 * resolved array so the real `Clients.matchAll` (which returns
 * `Promise<readonly WindowClient[]>`) satisfies this without a cast. */
export interface ClientsLike {
  matchAll(options: {
    type: "window"
    includeUncontrolled: boolean
  }): Promise<readonly ClientLike[]>
}

/**
 * Ask every open page what the caller's live widget data is, and use
 * whichever answers first.
 *
 * Resolves null when no page is open, or when nothing answers within
 * `timeoutMs` — the normal state with the app closed, not an error. Mirrors
 * `sw.ts`'s own `requestContentFromClients` for the push handshake; kept as
 * a distinct function (not a shared, parameterised one) so this file stays
 * entirely `self`-free and independently testable.
 */
export async function requestWidgetDataFromClients(
  clients: ClientsLike,
  timeoutMs: number,
): Promise<unknown> {
  const matched = await clients.matchAll({ type: "window", includeUncontrolled: true })
  if (matched.length === 0) return null

  return await new Promise<unknown>((resolve) => {
    let settled = false
    const finish = (value: unknown): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(value)
    }

    // A page that never answers must not hold widget rendering open
    // indefinitely; a prompt fallback to the stub beats a slow real answer.
    const timer = setTimeout(() => {
      finish(null)
    }, timeoutMs)

    // Widget bridge review fix (HIGH 1): one `MessageChannel` PER CLIENT, not
    // one shared channel whose `port2` was transferred to every client in
    // the loop. Structured-clone-with-transfer detaches a port on its first
    // transfer, so transferring the same already-detached `port2` to a
    // second client threw `DataCloneError` — inside this executor, which
    // rejected the whole promise instead of resolving null, so
    // `fetchWidgetDataOrStub` propagated the rejection and the widget
    // rendered NOTHING at all (not even the stub) whenever two or more tabs
    // were open — defeating the one guarantee this handshake exists to keep.
    // Only the first answer is used, so asking every page still costs
    // nothing; `finish`'s `settled` guard is what enforces that.
    for (const client of matched) {
      const channel = new MessageChannel()
      channel.port1.onmessage = (event: MessageEvent) => {
        finish(event.data)
      }
      client.postMessage({ type: WIDGET_DATA_REQUEST }, [channel.port2])
    }
  })
}

/**
 * Live data if a page answers with something usable, else the static stub.
 *
 * `fetchImpl` and `stubUrl` are passed in rather than read from `fetch`/a
 * hardcoded path directly, so a test can supply both without needing a
 * real network — and so the caller can pass the real widget definition's
 * own `data` URL (`widget.definition.data`), keeping the stub's location a
 * single fact declared once, in `vite/manifest.ts`, rather than duplicated
 * here.
 */
export async function fetchWidgetDataOrStub(
  clients: ClientsLike,
  timeoutMs: number,
  stubUrl: string,
  fetchImpl: (url: string) => Promise<{ text(): Promise<string> }>,
): Promise<string> {
  const live = decideWidgetData(await requestWidgetDataFromClients(clients, timeoutMs))
  if (live !== null) return JSON.stringify(live)
  return await (await fetchImpl(stubUrl)).text()
}
