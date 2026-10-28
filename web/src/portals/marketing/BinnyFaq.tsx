/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useId, useRef, useState } from 'react'
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion'
import { Textarea } from '@/components/ui/textarea'
import { Button, buttonVariants } from '@/components/ui/button'
import { faqItems, marketingLinks } from './content'
import { useSceneMotion } from './useSceneMotion'
import { Binny, type BinnyMood } from './Binny'

const moods: BinnyMood[] = ['nerd', 'open', 'wink', 'happy', 'happy']
const answerMood = (id: string) =>
  moods[faqItems.findIndex((item) => item.id === id)] ?? 'idle'

export function BinnyFaq() {
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState<{ id: string; answered: boolean }[]>([])
  const { ref, enabled, reducedMotion, inView, pageVisible } =
    useSceneMotion<HTMLElement>()
  const pending = asked.find((item) => !item.answered)?.id
  const [mobileAnswer, setMobileAnswer] = useState('')
  const chatId = useId()
  const chatRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!pending || !inView || !pageVisible) return
    const answer = () =>
      setAsked((previous) =>
        previous.map((item) =>
          item.id === pending ? { ...item, answered: true } : item,
        ),
      )
    if (reducedMotion) {
      answer()
      return
    }
    const item = faqItems.find((item) => item.id === pending)!
    const timer = window.setTimeout(
      answer,
      850 + Math.min(600, item.answer.length * 2),
    )
    return () => window.clearTimeout(timer)
  }, [pending, inView, pageVisible, reducedMotion])
  useEffect(() => {
    if (chatRef.current)
      chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [asked])
  const email = `${marketingLinks.contact}?subject=${encodeURIComponent('A question for Lemely')}&body=${encodeURIComponent(question)}`
  return (
    <section ref={ref} id="faq" className="brand-faq brand-section">
      <div className="brand-wrap brand-faq-grid">
        <div>
          <span className="brand-label">FAQ</span>
          <h2>
            Questions?
            <br />
            Ask Binny.
          </h2>
          <p>Tap a question and Binny will answer.</p>
          <div className="brand-faq-chips">
            {faqItems.map((x) => (
              <Button
                key={x.id}
                variant="secondary"
                aria-controls={chatId}
                aria-expanded={asked.some((item) => item.id === x.id)}
                onClick={() =>
                  setAsked((previous) => [
                    ...previous.filter((item) => item.id !== x.id),
                    { id: x.id, answered: reducedMotion },
                  ])
                }
              >
                {x.question}
                <span aria-hidden="true">
                  {asked.some((item) => item.id === x.id && item.answered)
                    ? '✓'
                    : '+'}
                </span>
              </Button>
            ))}
          </div>
          <Binny
            className="brand-faq-mascot brand-faq-binny"
            active={enabled}
            mood={answerMood(mobileAnswer)}
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
                className="brand-faq-binny"
                mood={pending ? 'thinking' : answerMood(asked.at(-1)?.id ?? '')}
                active={enabled}
              />
              <div>
                <strong>Binny</strong>
                <span className="brand-label" role="status">
                  {pending ? 'THINKING' : 'READY TO HELP'}
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
              {asked.map(({ id, answered }) => {
                const item = faqItems.find((x) => x.id === id)!
                return (
                  <dl key={id}>
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
                )
              })}
            </div>
          </section>
          <div className="brand-contact">
            <Textarea
              label="Ask anything else"
              rows={2}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="What's on your mind?"
            />
            <div>
              <p>
                Opens your email app. Or email us at{' '}
                <a href={marketingLinks.contact}>contact@lemelyig.com</a>.
              </p>
              <a
                href={email}
                className={buttonVariants({ variant: 'primary', size: 'sm' })}
              >
                Open email
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
