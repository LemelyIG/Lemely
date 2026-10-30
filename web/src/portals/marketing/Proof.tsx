/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { proofMetrics } from './content'
import { ResponsiveDeck } from './ResponsiveDeck'
import { ProofMetric } from './ProofMetric'

export function Proof() {
  return (
    <section className="brand-proof brand-section" id="teachers">
      <div className="brand-wrap">
        <span className="brand-label">PROOF</span>
        <h2>
          Marked like an examiner.
          <br />
          <span>Proven paper by paper.</span>
        </h2>
        <ResponsiveDeck
          label="Marking results"
          className="brand-metrics"
          tone="dark"
        >
          {proofMetrics.map((x, index) => (
            <ProofMetric
              key={x.value}
              value={x.value}
              label={x.label}
              index={index}
            />
          ))}
        </ResponsiveDeck>
        <div className="brand-accuracy">
          <div>
            <span className="brand-label">ACCURACY VS. EXAMINERS</span>
            <h3>
              Within ±1 mark of a senior examiner on <span>98.7%</span> of
              questions.
            </h3>
            <p>
              Blind-marked sample of past-paper scripts. Anything Lemely is
              unsure of goes to you before it counts.
            </p>
          </div>
          <div className="brand-dot-grid" aria-hidden="true">
            {Array.from({ length: 50 }, (_, i) => (
              <i key={i} className={i === 33 ? 'brand-dot-check' : ''} />
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
