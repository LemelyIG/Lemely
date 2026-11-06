/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { ForwardArrow } from '@/components/ui/inline-arrow'
import type { CSSProperties } from 'react'
import { StackDeck } from './StackDeck'

const at = (delay: string, duration?: string) =>
  ({ '--d': delay, '--t': duration }) as CSSProperties

const tick = 'M2 9 L8 15 L20 2'
const cross = 'M4 2 L18 16 M18 2 L4 16'
const lines = [
  { text: 'v = d / t', code: 'M1', path: tick, write: '0.2s', draw: '0.9s' },
  { text: '= 1200 / 240', code: 'M1', path: tick, write: '0.5s', draw: '1.1s' },
  { text: '= 5', code: 'A0', path: cross, write: '0.8s', draw: '1.3s' },
]

function UploadArt() {
  return (
    <div className="how-art">
      <strong>Uploading 3 photos</strong>
      <div className="how-bar">
        <span data-anim className="a-grow" style={at('0.2s', '1.8s')} />
      </div>
      <span data-anim className="how-mono a-up" style={at('1.9s')}>
        3 PAGES · 6 ANSWERS READ
      </span>
    </div>
  )
}

function MarkedArt() {
  return (
    <div className="how-art">
      <div className="how-question">
        <span>
          <b>(a)</b> Calculate the average speed in m/s.
        </span>
        <strong>2/3</strong>
      </div>
      <div className="how-lines">
        {lines.map((line) => (
          <div className="how-line" key={line.text}>
            <span data-anim className="how-hand a-write" style={at(line.write)}>
              {line.text}
            </span>
            <svg
              width="20"
              height="18"
              viewBox="0 0 22 18"
              aria-hidden="true"
              fill="none"
              stroke="var(--brand-art-23)"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path
                d={line.path}
                pathLength="1"
                data-anim
                className="a-draw"
                style={at(line.draw)}
              />
            </svg>
            <span className="how-code">{line.code}</span>
          </div>
        ))}
      </div>
      <div className="how-conf">
        <div>
          <span>AI confidence</span>
          <span>96%</span>
        </div>
        <div className="how-conf-track">
          <span data-anim className="a-grow" style={at('1.5s')} />
        </div>
      </div>
    </div>
  )
}

function InsightsArt() {
  return (
    <div className="how-art">
      <div className="how-grade">
        <span>Predicted grade</span>
        <span className="how-chip" style={{ background: 'var(--brand-art-8)' }}>
          B
        </span>
        <span aria-hidden="true"><ForwardArrow /></span>
        <span data-anim className="a-pop" style={at('0.3s')}>
          <span
            className="how-chip"
            style={{ background: 'var(--brand-art-9)' }}
          >
            A
          </span>
        </span>
      </div>
      <div data-anim className="how-lost a-up" style={at('0.8s')}>
        <span>Units &amp; SI</span>
        <span>−4 MARKS</span>
      </div>
      <div data-anim className="how-report a-up" style={at('1.3s')}>
        <span aria-hidden="true">✓</span>
        Progress report sent to Layan's parents
      </div>
    </div>
  )
}

const cards = [
  {
    n: '01',
    title: 'Upload',
    caption: 'Snap a photo of any hand-written past paper.',
    art: <UploadArt />,
  },
  {
    n: '02',
    title: 'Marked',
    caption: 'Every line checked against the official mark scheme.',
    art: <MarkedArt />,
  },
  {
    n: '03',
    title: 'Insights',
    caption: 'Your grade, your weak spot and a report for home.',
    art: <InsightsArt />,
  },
]

/** Reference mobile "How it works": a three-card stack, not a scroll scene. */
export function MobileHow() {
  return (
    <section id="how" className="brand-how brand-section">
      <div className="brand-wrap how-mobile">
        <span className="how-eyebrow">HOW IT WORKS</span>
        <h2>
          Upload.
          <br />
          Marked.
          <br />
          <span>Insights.</span>
        </h2>
        <StackDeck label="How it works">
          {cards.map((card) => (
            <article className="how-card" key={card.n}>
              {card.art}
              <div className="how-caption">
                <span>{card.n}</span>
                <h3>{card.title}</h3>
                <p>{card.caption}</p>
              </div>
            </article>
          ))}
        </StackDeck>
      </div>
    </section>
  )
}
