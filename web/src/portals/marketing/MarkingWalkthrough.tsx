/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState } from 'react'
import { CloudArrowUp, Check, ArrowRight } from '@phosphor-icons/react'
import { Tabs, TabsList, TabsPanel } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

const steps = [
  {
    value: 'upload',
    label: '01 Upload',
    description:
      'Photograph a hand-written past paper or drop in a scan. Lemely reads every answer, working included.',
  },
  {
    value: 'marked',
    label: '02 Marked',
    description:
      'Method and accuracy marks are awarded line by line against the official mark scheme, each with a confidence score.',
  },
  {
    value: 'insights',
    label: '03 Insights',
    description:
      'Lost marks cluster into weak topics, the predicted grade updates, and a practice plan is ready.',
  },
]
const questions = {
  a: {
    label: 'Q3(a)',
    title: 'Average speed',
    score: '2 / 3',
    confidence: 96,
    scheme: 'A1 · 5 m/s. The unit is required for the accuracy mark.',
    rows: [
      ['M1', 'Recalls v = d / t', 'AWARDED'],
      ['M1', 'Converts and substitutes 1200 ÷ 240', 'AWARDED'],
      ['A1', 'Final answer 5, no unit', 'NOT AWARDED'],
    ],
  },
  b: {
    label: 'Q3(b)',
    title: 'Speed vs velocity',
    score: '1 / 1',
    confidence: 91,
    scheme: 'B1 · Velocity has direction / is a vector.',
    rows: [['B1', 'States velocity has a direction', 'AWARDED']],
  },
  c: {
    label: 'Q3(c)',
    title: 'Acceleration',
    score: '1 / 2',
    confidence: 72,
    scheme: 'A1 · 0.5 m/s². The unit is required for the accuracy mark.',
    rows: [
      ['M1', 'Uses a = Δv / t with 5 ÷ 10', 'AWARDED'],
      ['A1', '0.5 with unit m/s (needs m/s²)', 'CHECK'],
    ],
  },
} as const
type QuestionKey = keyof typeof questions

function MarkedPaper({ reviewed }: { reviewed: boolean }) {
  return (
    <div className="brand-script">
      <div className="brand-script-head">
        <span className="brand-label">PHYSICS · PAPER 4 · QUESTION 3</span>
        <strong>{reviewed ? '5' : '4'}/6</strong>
      </div>
      <p>A cyclist travels 1.2 km in 4.0 minutes.</p>
      <div>
        <p>
          (a) Calculate the average speed in m/s. <span>[3]</span>
        </p>
        <div className="brand-working">
          <span>
            v = d / t <b>M1</b>
          </span>
          <span>
            = 1200 / 240 <b>M1</b>
          </span>
          <span>
            = 5 <b className="brand-wrong">A0</b>
          </span>
        </div>
      </div>
      <div>
        <p>
          (b) State one difference between speed and velocity. <span>[1]</span>
        </p>
        <div className="brand-working">
          <span>
            velocity has a direction <b>B1</b>
          </span>
        </div>
      </div>
      <div>
        <p>
          (c) It accelerates from rest to 5.0 m/s in 10 s. Calculate the
          acceleration. <span>[2]</span>
        </p>
        <div className="brand-working">
          <span>
            a = v / t = 5 / 10 <b>M1</b>
          </span>
          <span>
            = 0.5 m/s{' '}
            <b className={reviewed ? '' : 'brand-wrong'}>
              {reviewed ? 'A1' : 'A0'}
            </b>
          </span>
        </div>
      </div>
      <span className="brand-label">ILLUSTRATIVE MARKED ANSWER</span>
    </div>
  )
}

export function MarkingWalkthrough() {
  const [step, setStep] = useState('marked')
  const [question, setQuestion] = useState<QuestionKey>('a')
  const [review, setReview] = useState('keep')
  const selected = questions[question]
  return (
    <section id="how" className="brand-how brand-section">
      <div className="brand-wrap">
        <span className="brand-label">HOW IT WORKS</span>
        <h2>Upload. Marked. Insights.</h2>
        <Tabs
          value={step}
          onValueChange={setStep}
          className="brand-walkthrough"
        >
          <div className="brand-step-nav">
            <TabsList tabs={steps} label="Marking walkthrough" />
            <p>{steps.find((x) => x.value === step)?.description}</p>
            <span className="brand-label">A SAMPLE PAPER, EXPLAINED</span>
          </div>
          <div className="brand-stage">
            <TabsPanel value="upload">
              <div className="brand-upload">
                <CloudArrowUp size={64} aria-hidden="true" />
                <h3>Uploading 3 photos</h3>
                <div className="brand-photo-stack" aria-hidden="true">
                  <i />
                  <i />
                  <i>
                    <span className="brand-hand">
                      v = d / t<br />= 1200 / 240
                      <br />= 5
                    </span>
                  </i>
                </div>
                <p>
                  <Check aria-hidden="true" /> 3 pages received
                </p>
                <p>
                  <Check aria-hidden="true" /> Handwriting read · 6 answers
                </p>
                <p className="brand-label">Matching to the 0625 mark scheme…</p>
                <p>
                  Any phone camera. Crooked pages, pencil and crossings-out are
                  fine.
                </p>
              </div>
            </TabsPanel>
            <TabsPanel value="marked">
              <div className="brand-marked-grid">
                <MarkedPaper reviewed={review === 'award'} />
                <div className="brand-explanation">
                  <span className="brand-label">
                    TAP A QUESTION ON THE PAPER
                  </span>
                  <Tabs
                    value={question}
                    onValueChange={(v) => setQuestion(v as QuestionKey)}
                  >
                    <TabsList
                      tabs={Object.entries(questions).map(([value, q]) => ({
                        value,
                        label: q.label,
                      }))}
                      label="Question explanation"
                    />
                    {(Object.keys(questions) as QuestionKey[]).map((key) => (
                      <TabsPanel key={key} value={key}>
                        <div className="brand-explanation-title">
                          <h3>
                            {selected.label} · {selected.title}
                          </h3>
                          <strong>
                            {question === 'c' && review === 'award'
                              ? '2 / 2'
                              : selected.score}
                          </strong>
                        </div>
                        <div className="brand-mark-rows">
                          {selected.rows.map(([code, text, result], i) => (
                            <div key={i}>
                              <b>{code}</b>
                              <span>{text}</span>
                              <small
                                className={
                                  result === 'AWARDED'
                                    ? 'brand-correct'
                                    : 'brand-wrong'
                                }
                              >
                                {question === 'c' &&
                                i === 1 &&
                                review === 'award'
                                  ? 'AWARDED'
                                  : result}
                              </small>
                            </div>
                          ))}
                        </div>
                        <p className="brand-confidence">
                          AI confidence {selected.confidence}%
                        </p>
                        <div className="brand-confidence-track">
                          <span style={{ width: `${selected.confidence}%` }} />
                        </div>
                        <aside className="brand-scheme">
                          <span className="brand-label">
                            MARK SCHEME · 0625 · {selected.label}
                          </span>
                          <p>{selected.scheme}</p>
                        </aside>
                        {question === 'c' && (
                          <div className="brand-review">
                            <h4>Teacher review.</h4>
                            <p>
                              The unit looks like m/s, but the ² may be faint.
                              Sent to your queue before it counts.
                            </p>
                            <ToggleGroup
                              type="single"
                              value={review}
                              onValueChange={(v) => v && setReview(v)}
                              aria-label="Illustrative teacher review"
                            >
                              <ToggleGroupItem value="keep">
                                Keep A0
                              </ToggleGroupItem>
                              <ToggleGroupItem value="award">
                                Award A1
                              </ToggleGroupItem>
                            </ToggleGroup>
                            <p role="status">
                              Illustration:{' '}
                              {review === 'award' ? 'A1 awarded' : 'A0 kept'}
                            </p>
                          </div>
                        )}
                      </TabsPanel>
                    ))}
                  </Tabs>
                </div>
              </div>
            </TabsPanel>
            <TabsPanel value="insights">
              <div className="brand-insights">
                <div>
                  <span className="brand-label">ACROSS 3 PAPERS</span>
                  <h3>Weak topic found</h3>
                  <strong>Units &amp; SI</strong>
                  <div className="brand-topic-list">
                    <span>
                      P4 Q3(a) <b>−1</b>
                    </span>
                    <span>
                      P4 Q3(c) <b>−1</b>
                    </span>
                    <span>
                      P2 Q5 <b>−2</b>
                    </span>
                  </div>
                </div>
                <div>
                  <span className="brand-label">PREDICTED GRADE</span>
                  <p className="brand-grade-transition">
                    B <ArrowRight aria-hidden="true" /> A
                  </p>
                  <p>
                    Next: units drill · 10 questions{' '}
                    <span className="brand-label">15 MIN</span>
                  </p>
                  <p className="brand-report">
                    Progress report ready to send to Layan's parents.
                  </p>
                  <span className="brand-label">
                    ILLUSTRATION · NO REPORT IS SENT
                  </span>
                </div>
              </div>
            </TabsPanel>
          </div>
        </Tabs>
      </div>
    </section>
  )
}
