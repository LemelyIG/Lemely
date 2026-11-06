import { afterEach, describe, expect, it, vi } from "vitest"

import {
  ContactSendError,
  contactFailureCopy,
  sendContactMessage,
} from "@/portals/marketing/contact-api"

/*
 * The FAQ composer's send helper. The runner is node-only (no jsdom), so the
 * component's disabled-while-pending and keep-the-form-on-failure behaviour is
 * exercised by the marketing Playwright spec; the wire contract and the error
 * copy are pinned here.
 */

afterEach(() => vi.unstubAllGlobals())

describe("sendContactMessage", () => {
  it("POSTs the email and message as JSON with no Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 202 }))
    vi.stubGlobal("fetch", fetchMock)

    await sendContactMessage("a@b.co", "Can we arrange a demo?")

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe("/api/contact")
    expect(init.method).toBe("POST")
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@b.co",
      message: "Can we arrange a demo?",
    })
    expect(init.headers).not.toHaveProperty("Authorization")
  })

  it("throws with the status on a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 429 })))
    await expect(sendContactMessage("a@b.co", "hi")).rejects.toMatchObject({
      name: "ContactSendError",
      status: 429,
    })
  })

  it("throws status 0 when the network fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")))
    await expect(sendContactMessage("a@b.co", "hi")).rejects.toMatchObject({ status: 0 })
  })
})

describe("contactFailureCopy", () => {
  it("tells a rate-limited visitor to wait", () => {
    expect(contactFailureCopy(new ContactSendError(429))).toBe(
      "Too many messages. Try again in a few minutes.",
    )
  })

  it.each([0, 400, 502])("falls back to the email address for status %i", (status) => {
    expect(contactFailureCopy(new ContactSendError(status))).toBe(
      "Couldn't send that. Email contact@lemelyig.com instead.",
    )
  })
})
