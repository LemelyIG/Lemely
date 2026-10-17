import { describe, expect, it, vi } from "vitest"
import {
  WIDGET_DATA_REQUEST,
  decideWidgetData,
  fetchWidgetDataOrStub,
  requestWidgetDataFromClients,
  type ClientLike,
  type ClientsLike,
} from "@/sw/widgetBridge"

/**
 * Packet: wire the widget service-worker bridge (blocking, Phase A).
 *
 * Same reason, same shape as `sw/shareTarget.ts`: no `self`, no real
 * `Client`/`Clients` types — `ClientLike`/`ClientsLike` are narrowed down to
 * exactly what this file reads, so a fake can be built under this suite's
 * plain-Node vitest environment (no jsdom, no `ServiceWorkerGlobalScope`,
 * D3.20) instead of only pinning `sw.ts`'s wiring as a source-text gate.
 * `MessageChannel` is a real Node global (has been since Node 15), so the
 * handshake itself — not just the data shape — is exercised for real here.
 */

describe("decideWidgetData", () => {
  it("accepts a streak with no next session", () => {
    expect(decideWidgetData({ streak: 5, nextSession: null })).toEqual({
      streak: 5,
      nextSession: null,
    })
  })

  it("accepts a streak with a valid next session", () => {
    const reply = { streak: 12, nextSession: { title: "Momentum", startsAt: "2026-09-11T12:00:00Z" } }
    expect(decideWidgetData(reply)).toEqual(reply)
  })

  it("rejects a non-object reply", () => {
    expect(decideWidgetData(null)).toBeNull()
    expect(decideWidgetData(undefined)).toBeNull()
    expect(decideWidgetData("nope")).toBeNull()
  })

  it("rejects a non-numeric or negative streak", () => {
    expect(decideWidgetData({ streak: "5", nextSession: null })).toBeNull()
    expect(decideWidgetData({ streak: -1, nextSession: null })).toBeNull()
    expect(decideWidgetData({ streak: Number.NaN, nextSession: null })).toBeNull()
  })

  it("rejects a next session missing either field", () => {
    expect(decideWidgetData({ streak: 3, nextSession: { title: "Momentum" } })).toBeNull()
    expect(
      decideWidgetData({ streak: 3, nextSession: { startsAt: "2026-09-11T12:00:00Z" } }),
    ).toBeNull()
    expect(decideWidgetData({ streak: 3, nextSession: { title: "", startsAt: "" } })).toBeNull()
  })
})

/**
 * Widget bridge review fix (MEDIUM 1): a fake `ClientLike` whose
 * `postMessage` performs a REAL transfer of the port it's given, rather
 * than just calling `.postMessage()` on the very same `MessagePort` object
 * the production code handed it. The distinction matters: the earlier
 * version of this test file did the latter, which never detaches anything
 * and so could not have caught HIGH 1 — `requestWidgetDataFromClients`
 * transferring one shared `MessageChannel`'s `port2` to every client in a
 * loop, which throws a real `DataCloneError` on the second client because
 * structured-clone-with-transfer detaches a port on its first transfer.
 *
 * Bouncing `message`/`transfer` through a throwaway relay channel is what
 * forces Node's real WHATWG transfer algorithm to run on every object in
 * `transfer` — genuinely detaching a `MessagePort` the same way handing it
 * to a real browsing context would, so a caller that reuses an
 * already-transferred port on a second call gets the real `DataCloneError`,
 * not a silent no-op.
 */
function fakeClientWithRealTransfer(reply: unknown): ClientLike {
  return {
    postMessage: (message, transfer) => {
      const relay = new MessageChannel()
      relay.port2.onmessage = (event: MessageEvent) => {
        const port = event.ports[0] as MessagePort
        port.postMessage(reply)
      }
      relay.port1.postMessage(message, transfer)
    },
  }
}

describe("requestWidgetDataFromClients", () => {
  it("resolves null immediately when no page is open", async () => {
    const clients: ClientsLike = { matchAll: vi.fn().mockResolvedValue([]) }
    const result = await requestWidgetDataFromClients(clients, 1000)
    expect(result).toBeNull()
  })

  it("resolves with the first reply a client posts back", async () => {
    const client: ClientLike = {
      postMessage: (message, transfer) => {
        expect((message as { type: string }).type).toBe(WIDGET_DATA_REQUEST)
        const port = transfer[0] as MessagePort
        port.postMessage({ streak: 4, nextSession: null })
      },
    }
    const clients: ClientsLike = { matchAll: vi.fn().mockResolvedValue([client]) }

    const result = await requestWidgetDataFromClients(clients, 1000)
    expect(result).toEqual({ streak: 4, nextSession: null })
  })

  it("resolves null when the timeout elapses with no reply", async () => {
    const client: ClientLike = { postMessage: () => {} }
    const clients: ClientsLike = { matchAll: vi.fn().mockResolvedValue([client]) }

    const result = await requestWidgetDataFromClients(clients, 10)
    expect(result).toBeNull()
  })

  it("resolves — does not reject with DataCloneError — with two open tabs, each given its own port to transfer (HIGH 1 regression gate)", async () => {
    const clientA = fakeClientWithRealTransfer({ streak: 4, nextSession: null })
    const clientB = fakeClientWithRealTransfer({ streak: 9, nextSession: null })
    const clients: ClientsLike = { matchAll: vi.fn().mockResolvedValue([clientA, clientB]) }

    // Before the fix, this rejected with "DataCloneError: MessagePort in
    // transfer list is already detached" — the second client's transfer of
    // the first client's already-transferred shared `port2`. `resolves.not`
    // fails loudly (a rejection, not a resolved `null`) if that regresses.
    await expect(requestWidgetDataFromClients(clients, 1000)).resolves.toEqual(
      expect.objectContaining({ streak: expect.any(Number) }),
    )
  })
})

describe("fetchWidgetDataOrStub", () => {
  it("returns live data, stringified, without touching the stub fetch", async () => {
    const client: ClientLike = {
      postMessage: (_message, transfer) => {
        const port = transfer[0] as MessagePort
        port.postMessage({ streak: 7, nextSession: null })
      },
    }
    const clients: ClientsLike = { matchAll: vi.fn().mockResolvedValue([client]) }
    const fetchImpl = vi.fn()

    const data = await fetchWidgetDataOrStub(clients, 1000, "/widgets/streak-data.json", fetchImpl)

    expect(JSON.parse(data)).toEqual({ streak: 7, nextSession: null })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it("falls back to the stub when no client answers", async () => {
    const clients: ClientsLike = { matchAll: vi.fn().mockResolvedValue([]) }
    const stubText = '{"streak":0,"nextSession":null}'
    const fetchImpl = vi.fn().mockResolvedValue({ text: () => Promise.resolve(stubText) })

    const data = await fetchWidgetDataOrStub(clients, 1000, "/widgets/streak-data.json", fetchImpl)

    expect(fetchImpl).toHaveBeenCalledWith("/widgets/streak-data.json")
    expect(data).toBe(stubText)
  })

  it("falls back to the stub when a client answers with something unusable", async () => {
    const client: ClientLike = {
      postMessage: (_message, transfer) => {
        const port = transfer[0] as MessagePort
        port.postMessage({ streak: -1 })
      },
    }
    const clients: ClientsLike = { matchAll: vi.fn().mockResolvedValue([client]) }
    const stubText = '{"streak":0,"nextSession":null}'
    const fetchImpl = vi.fn().mockResolvedValue({ text: () => Promise.resolve(stubText) })

    const data = await fetchWidgetDataOrStub(clients, 1000, "/widgets/streak-data.json", fetchImpl)

    expect(data).toBe(stubText)
  })
})
