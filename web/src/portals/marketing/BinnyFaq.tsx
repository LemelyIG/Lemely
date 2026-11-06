/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Fragment, useEffect, useId, useRef, useState } from 'react'
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { faqItems, marketingLinks } from './content'
import { faqClosingNote, sendReply } from './faq-content'
import { useSceneMotion } from './useSceneMotion'
import { contactFailureCopy, sendContactMessage } from './contact-api'
import { Binny, type BinnyMood } from './Binny'

const moods: BinnyMood[] = ['nerd', 'open', 'wink', 'happy', 'happy']
const moodOf = (id: string) =>
  moods[faqItems.findIndex((item) => item.id === id)] ?? 'open'

/** A question Binny answers, or what the visitor typed into the composer (answered at once). */
type Turn = { id: string; answered: boolean } | { sent: string }
const isQuestion = (turn: Turn): turn is { id: string; answered: boolean } =>
  'id' in turn
/**
 * `doneAt` is the turn whose answer completed the set: the closing note follows it.
 * `happy` is the composer's Send: Binny's face stays happy until the next ask or answer.
 */
type Chat = { turns: Turn[]; doneAt: number; happy: boolean }

const answerTurn = (chat: Chat, index: number): Chat => {
  const turns = chat.turns.map((turn, i) =>
    i === index && isQuestion(turn) ? { ...turn, answered: true } : turn,
  )
  const everyAsked =
    new Set(turns.filter(isQuestion).map((turn) => turn.id)).size ===
    faqItems.length
  return {
    turns,
    doneAt: chat.doneAt < 0 && everyAsked ? index : chat.doneAt,
    happy: false,
  }
}

export function BinnyFaq() {
  const [question, setQuestion] = useState('')
  const [replyTo, setReplyTo] = useState('')
  const [chat, setChat] = useState<Chat>({ turns: [], doneAt: -1, happy: false })
  const { ref, enabled, reducedMotion, inView, pageVisible } =
    useSceneMotion<HTMLElement>()
  const pending = chat.turns.findIndex(
    (turn) => isQuestion(turn) && !turn.answered,
  )
  const [sentTo, setSentTo] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [mobileAnswer, setMobileAnswer] = useState('')
  const chatId = useId()
  const chatRef = useRef<HTMLDivElement>(null)
  const ask = (id: string) =>
    setChat((previous) => {
      // One question at a time, as in the reference: asking while Binny types does nothing.
      if (previous.turns.some((turn) => isQuestion(turn) && !turn.answered))
        return previous
      const next = {
        turns: [...previous.turns, { id, answered: false }],
        doneAt: previous.doneAt,
        happy: false,
      }
      return reducedMotion ? answerTurn(next, next.turns.length - 1) : next
    })
  useEffect(() => {
    if (pending < 0 || !inView || !pageVisible) return
    if (reducedMotion) {
      setChat((previous) => answerTurn(previous, pending))
      return
    }
    const item = faqItems.find(
      (item) => item.id === (chat.turns[pending] as { id: string }).id,
    )!
    const timer = window.setTimeout(
      () => setChat((previous) => answerTurn(previous, pending)),
      900 + Math.min(900, item.answer.length * 4),
    )
    return () => window.clearTimeout(timer)
  }, [pending, inView, pageVisible, reducedMotion, chat.turns])
  useEffect(() => {
    if (chatRef.current)
      chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [chat])
  const asked = new Set(chat.turns.filter(isQuestion).map((turn) => turn.id))
  const lastAnswered = chat.turns.findLast(
    (turn) => isQuestion(turn) && turn.answered,
  ) as { id: string } | undefined
  const canSend = /.+@.+\..+/.test(replyTo) && question.trim() !== ''
  const send = async () => {
    if (!canSend || sending) return
    setSending(true)
    setSendError('')
    try {
      await sendContactMessage(replyTo, question.trim())
    } catch (error) {
      setSendError(contactFailureCopy(error))
      setSending(false)
      return
    }
    setSending(false)
    setChat((previous) => ({
      ...previous,
      turns: [...previous.turns, { sent: question }],
      happy: true,
    }))
    setSentTo(replyTo)
    chatRef.current?.focus({ preventScroll: true })
  }
  return (
    <section ref={ref} id="faq" className="brand-faq brand-section">
      <div className="brand-wrap brand-faq-grid">
        <div>
          <span className="brand-label">FAQ</span>
          <h2>
            Questions?
            <br />
            <span>Ask Binny.</span>
          </h2>
          <p>Tap a question and Binny will answer.</p>
          <div className="brand-faq-chips">
            {faqItems.map((x) => (
              <Button
                key={x.id}
                variant="secondary"
                aria-controls={chatId}
                aria-expanded={asked.has(x.id)}
                onClick={() => ask(x.id)}
              >
                {x.question}
                <span aria-hidden="true">
                  {asked.has(x.id) ? 'ASKED' : 'ASK'}
                </span>
              </Button>
            ))}
          </div>
          <Binny
            className="brand-faq-mascot brand-faq-binny"
            compact
            mood={moodOf(mobileAnswer)}
          />
        </div>
        <div className="brand-faq-panel">
          <div className="brand-faq-mobile">
            <Accordion
              type="single"
              collapsible
              value={mobileAnswer}
              onValueChange={setMobileAnswer}
            >
              {faqItems.map((x) => (
                <AccordionItem key={x.id} value={x.id}>
                  <AccordionTrigger>{x.question}</AccordionTrigger>
                  <AccordionContent>{x.answer}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
          <section className="brand-conversation" aria-label="Binny answers">
            <header>
              <Binny
                compact
                className="brand-faq-binny"
                mood={
                  chat.happy
                    ? 'happy'
                    : pending >= 0
                      ? 'thinking'
                      : moodOf(lastAnswered?.id ?? '')
                }
              />
              <div>
                <strong>Binny</strong>
                <span
                  className="brand-label"
                  role="status"
                  data-typing={pending >= 0 ? '' : undefined}
                >
                  {pending >= 0 ? 'TYPING…' : 'ONLINE · ANSWERS IN SECONDS'}
                </span>
              </div>
            </header>
            <div
              ref={chatRef}
              id={chatId}
              role="log"
              aria-label="Questions and answers"
              aria-live="polite"
              tabIndex={0}
              className="brand-conversation-log"
              data-motion={enabled ? 'active' : 'still'}
            >
              <p>Got questions? I've got answers. Mostly correct ones.</p>
              {chat.turns.map((turn, index) => {
                if (!isQuestion(turn))
                  return (
                    <dl key={index}>
                      <dt>{turn.sent}</dt>
                      <dd>{sendReply}</dd>
                    </dl>
                  )
                const { id, answered } = turn
                const item = faqItems.find((x) => x.id === id)!
                return (
                  <Fragment key={index}>
                    <dl>
                      <dt>{item.question}</dt>
                      {answered ? (
                        <dd>{item.answer}</dd>
                      ) : (
                        <dd
                          className="brand-typing"
                          aria-label="Binny is thinking"
                        >
                          <i />
                          <i />
                          <i />
                        </dd>
                      )}
                    </dl>
                    {index === chat.doneAt && <p>{faqClosingNote}</p>}
                  </Fragment>
                )
              })}
            </div>
          </section>
          <div className="brand-contact">
            {sentTo === '' ? (
              <>
                <Textarea
                  label="Ask anything else"
                  rows={2}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Your question"
                />
                <div className="brand-contact-row">
                  <Input
                    type="email"
                    label="Your email"
                    labelClassName="sr-only"
                    wrapperClassName="brand-contact-email"
                    value={replyTo}
                    onChange={(e) => setReplyTo(e.target.value)}
                    placeholder="Your email"
                    autoComplete="email"
                  />
                  <Button
                    type="button"
                    variant="primary"
                    className="brand-contact-send"
                    disabled={!canSend || sending}
                    aria-busy={sending}
                    onClick={() => void send()}
                  >
                    Send
                  </Button>
                </div>
                {sendError !== '' && (
                  <span className="brand-contact-error" role="alert">
                    {sendError}
                  </span>
                )}
                <span className="brand-contact-alt">
                  Or email us at{' '}
                  <a href={marketingLinks.contact}>contact@lemelyig.com</a>
                </span>
              </>
            ) : (
              <div className="brand-contact-sent" role="status">
                <span aria-hidden="true">
                  <svg viewBox="0 0 16 16" width="14" height="14" fill="none">
                    <path
                      d="M3 8.5 6.5 12 13 4.5"
                      stroke="currentColor"
                      strokeWidth="2.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                <span>
                  Got it. We'll email you back at <b>{sentTo}</b>.
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
