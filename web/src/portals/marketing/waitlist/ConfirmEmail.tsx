/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { BinnyMood } from '../Binny'
import { PeekBinny } from '@/portals/access/PeekBinny'
import {
  classifyConfirmFailure,
  confirmWaitlist,
  type WaitlistConfirmFailure,
  type WaitlistConfirmResult,
} from '@/lib/waitlist-api'
import { useWaitlist } from './WaitlistDialog'
import './confirm.css'

/*
 * `/waitlist/confirm?token=…`: the page the confirmation email links to. Public, outside the
 * access gate. It reads the token once, takes it out of the address bar, and confirms.
 *
 * One request per token: React strict mode runs the effect twice in development, and a second
 * POST would answer "already confirmed" and hide the real result.
 */

export type ConfirmState =
  | { kind: 'loading' }
  | { kind: 'confirmed' }
  | { kind: 'already' }
  | { kind: 'failed'; reason: WaitlistConfirmFailure }

const inflight = new Map<string, Promise<WaitlistConfirmResult>>()

function confirmOnce(token: string): Promise<WaitlistConfirmResult> {
  let call = inflight.get(token)
  if (!call) {
    call = confirmWaitlist(token)
    inflight.set(token, call)
    // A failure may be retried (rate limit, network): do not keep it.
    call.catch(() => inflight.delete(token))
  }
  return call
}

function readToken(): string {
  return new URLSearchParams(window.location.search).get('token')?.trim() ?? ''
}

const SHARE_URL = () =>
  `${window.location.origin}/landing?utm_source=waitlist_share&utm_medium=share&utm_campaign=confirm`

interface Copy {
  /** Binny's starting expression, then the ones a tap cycles through. */
  moods: BinnyMood[]
  bubble: string
  title: string
  /** The tail of `title` that gets the highlighter. */
  accent: string
  body: string
}

const TAP = ['happy', 'wink', 'open'] as const

/** What each state says. Short, honest, in Binny's voice, no dates or counts. */
export function confirmCopy(state: ConfirmState): Copy {
  if (state.kind === 'loading')
    return { moods: ['thinking', ...TAP], bubble: 'One sec.', title: 'Checking your link', accent: 'your link', body: 'Binny is on it.' }
  if (state.kind === 'confirmed')
    return {
      moods: ['happy', 'wink', 'open', 'nerd'],
      bubble: 'Nice one.',
      title: 'Confirmed. Binny approves.', accent: 'Binny approves.',
      body: "Thanks. We'll email you when access opens.",
    }
  if (state.kind === 'already')
    return {
      moods: ['wink', ...TAP],
      bubble: 'Twice is fine.',
      title: 'Already confirmed.', accent: 'confirmed.',
      body: "Binny checked twice. You're all set, and we'll email you when access opens.",
    }
  switch (state.reason) {
    case 'expired':
      return {
        moods: ['thinking', ...TAP],
        bubble: 'That one timed out.',
        title: 'That link has expired.', accent: 'expired.',
        body: "Enter your email on the waitlist form again and we'll send a new one.",
      }
    case 'invalid':
      return {
        moods: ['thinking', ...TAP],
        bubble: 'Hmm, not this one.',
        title: "That link doesn't work.", accent: "doesn't work.",
        body: "Binny can't make sense of it. Enter your email on the waitlist form again and we'll send a new one.",
      }
    case 'rate':
      return { moods: ['open', ...TAP], bubble: 'Easy, easy.', title: 'Slow down a little.', accent: 'a little.', body: 'Wait a few minutes, then try again.' }
    default:
      return { moods: ['thinking', ...TAP], bubble: 'Lost the signal.', title: 'Binny lost the signal.', accent: 'the signal.', body: 'Check your connection and try again.' }
  }
}

function ShareButton() {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const t = window.setTimeout(() => setCopied(false), 2000)
    return () => window.clearTimeout(t)
  }, [copied])
  const share = async () => {
    const url = SHARE_URL()
    try {
      if (navigator.share) {
        await navigator.share({ title: 'Lemely', text: 'Lemely: every mark, explained.', url })
        return
      }
      await navigator.clipboard.writeText(url)
      setCopied(true)
    } catch {
      // A dismissed share sheet or a blocked clipboard is not an error worth a message.
    }
  }
  return (
    <button type="button" onClick={() => void share()}>
      {copied ? 'Link copied' : 'Share Lemely'}
    </button>
  )
}

/** The view for one state, with no network: the preview and the tests render it directly. */
export function ConfirmEmailView({ state, onRetry }: { state: ConfirmState; onRetry?: () => void }) {
  const waitlist = useWaitlist()
  const copy = confirmCopy(state)
  const key = state.kind === 'failed' ? `failed-${state.reason}` : state.kind
  const retryable = state.kind === 'failed' && (state.reason === 'rate' || state.reason === 'network' || state.reason === 'other')
  const relink = state.kind === 'failed' && (state.reason === 'invalid' || state.reason === 'expired')
  const accentAt = copy.title.endsWith(copy.accent) ? copy.title.length - copy.accent.length : copy.title.length
  return (
    <div className="cf-page" data-state={state.kind === 'failed' ? state.reason : state.kind}>
      <div className="cf-copy" role="status" aria-live="polite">
        <h1 className="cf-title" tabIndex={-1} ref={(el) => el?.focus({ preventScroll: true })}>
          {copy.title.slice(0, accentAt)}
          <span className="cf-mark">{copy.title.slice(accentAt)}</span>
        </h1>
        <p className="cf-body">{copy.body}</p>
        {state.kind !== 'loading' ? (
          <div className="brand-actions cf-actions">
            {state.kind === 'confirmed' ? <ShareButton /> : null}
            {relink ? (
              <button type="button" onClick={(e) => waitlist.open(e.currentTarget)}>
                Join the waitlist
              </button>
            ) : null}
            {retryable ? (
              <button type="button" onClick={onRetry}>
                Try again
              </button>
            ) : null}
            <Link to="/landing">Back to the landing page</Link>
          </div>
        ) : null}
      </div>
      <div className="cf-stage" key={key}>
        <Scene state={state} />
        <PeekBinny moods={copy.moods} bubble={copy.bubble} label="Say hi to Binny" />
      </div>
    </div>
  )
}

/** Decoration around Binny that tells the state at a glance: sparkles, question marks, z's, dots. Never read out. */
function Scene({ state }: { state: ConfirmState }) {
  const kind = state.kind === 'failed' ? state.reason : state.kind
  const items: Record<string, { cls: string; glyph?: string }[]> = {
    confirmed: [1, 2, 3, 4, 5].map((n) => ({ cls: `cf-sparkle cf-s${n}` })),
    already: [{ cls: 'cf-check cf-c1', glyph: '\u2713' }, { cls: 'cf-check cf-c2', glyph: '\u2713' }],
    invalid: [{ cls: 'cf-q cf-q1', glyph: '?' }, { cls: 'cf-q cf-q2', glyph: '?' }, { cls: 'cf-q cf-q3', glyph: '?' }],
    expired: [{ cls: 'cf-q cf-q1', glyph: '?' }, { cls: 'cf-q cf-q2', glyph: '?' }, { cls: 'cf-q cf-q3', glyph: '?' }],
    rate: [{ cls: 'cf-z cf-z1', glyph: 'z' }, { cls: 'cf-z cf-z2', glyph: 'z' }, { cls: 'cf-z cf-z3', glyph: 'z' }],
    network: [{ cls: 'cf-z cf-z1', glyph: 'z' }, { cls: 'cf-z cf-z2', glyph: 'z' }, { cls: 'cf-z cf-z3', glyph: 'z' }],
    other: [{ cls: 'cf-z cf-z1', glyph: 'z' }, { cls: 'cf-z cf-z2', glyph: 'z' }, { cls: 'cf-z cf-z3', glyph: 'z' }],
    loading: [{ cls: 'cf-dot cf-d1' }, { cls: 'cf-dot cf-d2' }, { cls: 'cf-dot cf-d3' }],
  }
  return (
    <div className="cf-scene" aria-hidden="true">
      {(items[kind] ?? []).map((it) => (
        <span key={it.cls} className={it.cls}>
          {it.glyph === '\u2713' ? (
            <svg className="cf-tick" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6.5 12.1l3.8 3.8 7.2-8" />
            </svg>
          ) : (
            it.glyph
          )}
        </span>
      ))}
    </div>
  )
}

export function ConfirmEmail() {
  const [token] = useState(readToken)
  const [state, setState] = useState<ConfirmState>(() => (token ? { kind: 'loading' } : { kind: 'failed', reason: 'invalid' }))
  const [attempt, setAttempt] = useState(0)

  // Take the token out of the address bar and the history entry once it is read.
  useEffect(() => {
    if (window.location.search) window.history.replaceState(window.history.state, '', window.location.pathname)
  }, [])

  useEffect(() => {
    if (!token) return
    let live = true
    confirmOnce(token).then(
      (result) => live && setState({ kind: result.status === 'confirmed' ? 'confirmed' : 'already' }),
      (error: unknown) => live && setState({ kind: 'failed', reason: classifyConfirmFailure(error) }),
    )
    return () => {
      live = false
    }
  }, [token, attempt])

  const retry = useCallback(() => {
    setState({ kind: 'loading' })
    setAttempt((n) => n + 1)
  }, [])

  useEffect(() => {
    document.title = 'Confirm your email | Lemely'
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex, nofollow'
    document.head.appendChild(meta)
    return () => meta.remove()
  }, [])

  return <ConfirmEmailView state={state} onRetry={retry} />
}
