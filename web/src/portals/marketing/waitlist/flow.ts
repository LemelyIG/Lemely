/**
 * Decisions in the two-step flow that must not depend on the DOM, so they can be tested.
 *
 * Step 1 creates the applicant and returns a one-time token. Once a token is held, email and
 * role are final (the server cannot change them), so Back then Continue goes straight to
 * step 2: calling the server again would answer "already listed", skip step 2 and throw away
 * the visitor's progress. A 400 on step 2 means the token expired or was used; the email is
 * still saved, so the flow ends there rather than restarting.
 */
import { WaitlistError, type WaitlistStep1Result } from '@/lib/waitlist-api'

export type ContinueAction = 'call-server' | 'go-step-2'

export function decideContinue(token: string): ContinueAction {
  return token ? 'go-step-2' : 'call-server'
}

export type Step2Failure = 'expired' | 'rate' | 'network' | 'failed'

export function classifyStep2Failure(error: unknown): Step2Failure {
  if (error instanceof WaitlistError) {
    if (error.status === 400) return 'expired'
    if (error.status === 429) return 'rate'
    if (error.status === 0) return 'network'
  }
  return 'failed'
}

export const EXPIRED_COPY =
  "Your email is saved. The details link expired, so we'll ask for the rest later."

/**
 * Continue on step 1. With a token held the server already knows this applicant, so go straight
 * to step 2 without calling `join` (a second call would answer "already listed" and drop step 2).
 * `join` does the validation and the call; it returns null when it stopped before calling.
 */
export async function continueStep1(
  token: string,
  join: () => Promise<WaitlistStep1Result | null>,
): Promise<{ kind: 'step-2'; token: string } | { kind: 'joined'; result: WaitlistStep1Result } | { kind: 'stopped' }> {
  if (decideContinue(token) === 'go-step-2') return { kind: 'step-2', token }
  const result = await join()
  return result ? { kind: 'joined', result } : { kind: 'stopped' }
}

/** Retry a flaky load a couple of times with a short back-off before giving up. */
export async function withRetry<T>(load: () => Promise<T>, delays: readonly number[] = [400, 1200]): Promise<T> {
  for (let i = 0; ; i++) {
    try {
      return await load()
    } catch (error) {
      if (i >= delays.length) throw error
      await new Promise((r) => setTimeout(r, delays[i]))
    }
  }
}

export const CONFIG_FAILED_COPY =
  "We couldn't load the security check. Try again, or email contact@lemelyig.com."
export const TURNSTILE_FAILED_COPY = "We couldn't check that you're a person. Try again."
