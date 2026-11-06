/**
 * The landing page's one write: the FAQ composer's question, emailed to the team.
 *
 * Deliberately not `request` from `@/lib/api`: the page is signed-out, and that
 * helper attaches a bearer token, refreshes it on 401 and can end the session.
 * None of that applies to an anonymous visitor, so this is a plain fetch that
 * throws on any non-2xx.
 */

export class ContactSendError extends Error {
  status: number

  constructor(status: number) {
    super(`Contact request failed with status ${status}`)
    this.name = 'ContactSendError'
    this.status = status
  }
}

/** Throws `ContactSendError` (status 0 when the request never got a response). */
export async function sendContactMessage(
  email: string,
  message: string,
): Promise<void> {
  let res: Response
  try {
    res = await fetch('/api/contact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, message }),
    })
  } catch {
    throw new ContactSendError(0)
  }
  if (!res.ok) throw new ContactSendError(res.status)
}

/** What the visitor reads under the composer after a failed send. */
export function contactFailureCopy(error: unknown): string {
  return error instanceof ContactSendError && error.status === 429
    ? 'Too many messages. Try again in a few minutes.'
    : "Couldn't send that. Email contact@lemelyig.com instead."
}
