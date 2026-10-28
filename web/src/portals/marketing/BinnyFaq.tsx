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

export function BinnyFaq() {
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState<string[]>([])
  const chatId = useId()
  const chatRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (chatRef.current)
      chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [asked])
  const email = `${marketingLinks.contact}?subject=${encodeURIComponent('A question for Lemely')}&body=${encodeURIComponent(question)}`
  return (
    <section id="faq" className="brand-faq brand-section">
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
                aria-expanded={asked.includes(x.id)}
                onClick={() =>
                  setAsked((previous) => [
                    ...previous.filter((id) => id !== x.id),
                    x.id,
                  ])
                }
              >
                {x.question}
                <span aria-hidden="true">
                  {asked.includes(x.id) ? '✓' : '+'}
                </span>
              </Button>
            ))}
          </div>
          <img
            className="brand-faq-mascot"
            src="/marketing/brand/binny.svg"
            width="220"
            height="220"
            alt="Binny, Lemely’s paperclip-eared mascot"
            loading="lazy"
          />
        </div>
        <div className="brand-faq-panel">
          <div className="brand-faq-mobile">
            <Accordion type="single" collapsible>
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
              <img
                src="/marketing/brand/binny.svg"
                width="52"
                height="52"
                alt=""
              />
              <div>
                <strong>Binny</strong>
                <span className="brand-label">READY TO HELP</span>
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
            >
              <p>Got questions? I've got answers. Mostly correct ones.</p>
              {asked.map((id) => {
                const item = faqItems.find((x) => x.id === id)!
                return (
                  <dl key={id}>
                    <dt>{item.question}</dt>
                    <dd>{item.answer}</dd>
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
