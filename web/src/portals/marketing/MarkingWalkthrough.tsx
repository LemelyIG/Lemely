/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useSceneMotion } from "./useSceneMotion";
import "./walkthrough-motion.css";
import { CloudArrowUp, Check, ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsPanel } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

const steps = [
  {
    value: "upload",
    label: "01 Upload",
    description:
      "Photograph a hand-written past paper or drop in a scan. Lemely reads every answer, working included.",
  },
  {
    value: "marked",
    label: "02 Marked",
    description:
      "Method and accuracy marks are awarded line by line against the official mark scheme, each with a confidence score.",
  },
  {
    value: "insights",
    label: "03 Insights",
    description:
      "Lost marks cluster into weak topics, the predicted grade updates, and a practice plan is ready.",
  },
];
const questions = {
  a: {
    label: "Q3(a)",
    title: "Average speed",
    score: "2 / 3",
    confidence: 96,
    scheme: "A1 · 5 m/s. The unit is required for the accuracy mark.",
    rows: [
      ["M1", "Recalls v = d / t", "AWARDED"],
      ["M1", "Converts and substitutes 1200 ÷ 240", "AWARDED"],
      ["A1", "Final answer 5, no unit", "NOT AWARDED"],
    ],
  },
  b: {
    label: "Q3(b)",
    title: "Speed vs velocity",
    score: "1 / 1",
    confidence: 91,
    scheme: "B1 · Velocity has direction / is a vector.",
    rows: [["B1", "States velocity has a direction", "AWARDED"]],
  },
  c: {
    label: "Q3(c)",
    title: "Acceleration",
    score: "1 / 2",
    confidence: 72,
    scheme: "A1 · 0.5 m/s². The unit is required for the accuracy mark.",
    rows: [
      ["M1", "Uses a = Δv / t with 5 ÷ 10", "AWARDED"],
      ["A1", "0.5 with unit m/s (needs m/s²)", "CHECK"],
    ],
  },
} as const;
type QuestionKey = keyof typeof questions;

function MarkedPaper({
  reviewed,
  unmarked = false,
  onSelect,
}: {
  reviewed: boolean;
  unmarked?: boolean;
  onSelect?: (question: QuestionKey) => void;
}) {
  return (
    <div className="brand-script" data-unmarked={unmarked}>
      {unmarked && <span className="walkthrough-scan" aria-hidden="true" />}
      <div className="brand-script-head">
        <span className="brand-label">PHYSICS · PAPER 4 · QUESTION 3</span>
        <strong>{reviewed ? "5" : "4"}/6</strong>
      </div>
      <p>A cyclist travels 1.2 km in 4.0 minutes.</p>
      <div>
        <p>
          <Button
            variant="ghost"
            className="walkthrough-paper-question"
            onClick={() => onSelect?.("a")}
            disabled={unmarked}
            aria-label="Explain Q3(a)"
          >
            (a)
          </Button>{" "}
          Calculate the average speed in m/s. <span>[3]</span>
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
          <Button
            variant="ghost"
            className="walkthrough-paper-question"
            onClick={() => onSelect?.("b")}
            disabled={unmarked}
            aria-label="Explain Q3(b)"
          >
            (b)
          </Button>{" "}
          State one difference between speed and velocity. <span>[1]</span>
        </p>
        <div className="brand-working">
          <span>
            velocity has a direction <b>B1</b>
          </span>
        </div>
      </div>
      <div>
        <p>
          <Button
            variant="ghost"
            className="walkthrough-paper-question"
            onClick={() => onSelect?.("c")}
            disabled={unmarked}
            aria-label="Explain Q3(c)"
          >
            (c)
          </Button>{" "}
          It accelerates from rest to 5.0 m/s in 10 s. Calculate the
          acceleration. <span>[2]</span>
        </p>
        <div className="brand-working">
          <span>
            a = v / t = 5 / 10 <b>M1</b>
          </span>
          <span>
            = 0.5 m/s{" "}
            <b className={reviewed ? "" : "brand-wrong"}>
              {reviewed ? "A1" : "A0"}
            </b>
          </span>
        </div>
      </div>
      <span className="brand-label">ILLUSTRATIVE MARKED ANSWER</span>
    </div>
  );
}

function WalkthroughPanel({
  value,
  flow,
  active,
  children,
}: {
  value: string;
  flow: boolean;
  active: boolean;
  children: ReactNode;
}) {
  if (!flow) return <TabsPanel value={value}>{children}</TabsPanel>;
  return (
    <section
      data-walkthrough-step={value}
      data-active={active}
      aria-label={steps.find((s) => s.value === value)?.label}
    >
      <h3 className="walkthrough-mobile-title">
        {steps.find((s) => s.value === value)?.label}
      </h3>
      <p className="walkthrough-mobile-description">
        {steps.find((s) => s.value === value)?.description}
      </p>
      {children}
    </section>
  );
}

export function MarkingWalkthrough() {
  const [step, setStep] = useState("upload");
  const [mobile, setMobile] = useState(
    () => window.matchMedia("(max-width: 759px)").matches,
  );
  const { ref, enabled, reducedMotion, pageVisible } =
    useSceneMotion<HTMLElement>();
  const fill = useRef<HTMLSpanElement>(null);
  // Focus and DOM layout may scroll a sticky child's original layout position.
  // Keep its stage mounted until the visitor deliberately scrolls again.
  const interacting = useRef(false);
  const [seen, setSeen] = useState<string[]>([]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 759px)");
    const change = () => setMobile(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);

  useEffect(() => {
    const element = ref.current;
    if (!element || !pageVisible) return;
    if (mobile) {
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              const value = (entry.target as HTMLElement).dataset
                .walkthroughStep!;
              setSeen((old) => (old.includes(value) ? old : [...old, value]));
            }
          });
        },
        { rootMargin: "0px 0px -20% 0px", threshold: 0 },
      );
      element
        .querySelectorAll("[data-walkthrough-step]")
        .forEach((node) => observer.observe(node));
      return () => observer.disconnect();
    }
    if (!enabled) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const bounds = element.getBoundingClientRect();
      const progress = Math.max(
        0,
        Math.min(
          1,
          -bounds.top / Math.max(1, bounds.height - window.innerHeight),
        ),
      );
      if (fill.current) fill.current.style.transform = `scaleX(${progress})`;
      if (!interacting.current)
        setStep(
          progress < 0.34 ? "upload" : progress < 0.7 ? "marked" : "insights",
        );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    const resumeScroll = () => {
      interacting.current = false;
      schedule();
    };
    const resumeOutside = (event: PointerEvent) => {
      if (
        !(event.target instanceof Element) ||
        !event.target.closest(".brand-marked-grid")
      )
        resumeScroll();
    };
    const resumeScrollKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isControl = target?.closest(
        "button, input, textarea, select, [role=tab], [role=radio], [contenteditable=true]",
      );
      if (
        ["PageDown", "PageUp"].includes(event.key) ||
        (!isControl &&
          ["ArrowDown", "ArrowUp", "Home", "End", " "].includes(event.key))
      )
        resumeScroll();
    };
    window.addEventListener("pointerdown", resumeOutside, true);
    window.addEventListener("wheel", resumeScroll, {
      passive: true,
      capture: true,
    });
    window.addEventListener("touchmove", resumeScroll, {
      passive: true,
      capture: true,
    });
    window.addEventListener("keydown", resumeScrollKey, true);
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("pointerdown", resumeOutside, true);
      window.removeEventListener("wheel", resumeScroll, true);
      window.removeEventListener("touchmove", resumeScroll, true);
      window.removeEventListener("keydown", resumeScrollKey, true);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      cancelAnimationFrame(frame);
    };
  }, [enabled, mobile, pageVisible, ref]);

  useEffect(() => {
    const grid = ref.current?.querySelector<HTMLElement>(".brand-walkthrough");
    if (!grid || mobile || reducedMotion) return;
    const fit = () => {
      grid.style.setProperty(
        "--walkthrough-scale",
        String(
          Math.min(
            1,
            (window.innerHeight - 112) / Math.max(1, grid.offsetHeight),
          ),
        ),
      );
    };
    const observer = new ResizeObserver(fit);
    observer.observe(grid);
    window.addEventListener("resize", fit);
    fit();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", fit);
      grid.style.removeProperty("--walkthrough-scale");
    };
  }, [mobile, reducedMotion, ref]);

  const selectStep = (value: string) => {
    setStep(value);
    if (mobile || reducedMotion || !ref.current) return;
    const bounds = ref.current.getBoundingClientRect();
    const progress =
      value === "upload" ? 0.08 : value === "marked" ? 0.5 : 0.85;
    window.scrollTo({
      top:
        window.scrollY +
        bounds.top +
        Math.max(0, bounds.height - window.innerHeight) * progress,
      behavior: "instant",
    });
  };
  const [question, setQuestion] = useState<QuestionKey>("a");
  const [review, setReview] = useState("keep");
  const selected = questions[question];
  return (
    <section
      id="how"
      ref={ref}
      className="brand-how brand-section walkthrough-motion"
      data-motion={enabled}
      data-reduced={reducedMotion}
    >
      <div className="brand-wrap">
        <Tabs
          value={step}
          onValueChange={(value) => {
            interacting.current = false;
            selectStep(value);
          }}
          className="brand-walkthrough"
        >
          <div className="brand-step-nav">
            <span className="brand-label">HOW IT WORKS · SCROLL</span>
            <h2>
              Upload.
              <br />
              Marked.
              <br />
              <span>Insights.</span>
            </h2>
            <div className="walkthrough-progress" aria-hidden="true">
              <span ref={fill} />
            </div>
            <div className="walkthrough-desktop-nav">
              <TabsList tabs={steps} label="Marking walkthrough" />
            </div>
            <p>{steps.find((x) => x.value === step)?.description}</p>
            <span className="brand-label">A SAMPLE PAPER, EXPLAINED</span>
          </div>
          <div className="brand-stage">
            <WalkthroughPanel
              value="upload"
              flow={mobile}
              active={reducedMotion || seen.includes("upload")}
            >
              <div className="walkthrough-upload-grid">
                {!mobile && <MarkedPaper reviewed={false} unmarked />}
                <div className="brand-upload">
                  <CloudArrowUp size={64} aria-hidden="true" />
                  <h3>Uploading 3 photos</h3>
                  <div
                    className="walkthrough-upload-progress"
                    aria-hidden="true"
                  >
                    <span />
                  </div>
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
                  <p className="brand-label">
                    Matching to the 0625 mark scheme…
                  </p>
                  <p>
                    Any phone camera. Crooked pages, pencil and crossings-out
                    are fine.
                  </p>
                </div>
              </div>
            </WalkthroughPanel>
            <WalkthroughPanel
              value="marked"
              flow={mobile}
              active={reducedMotion || seen.includes("marked")}
            >
              <div
                className="brand-marked-grid"
                onPointerDownCapture={() => {
                  if (!mobile && !reducedMotion) interacting.current = true;
                }}
                onFocusCapture={() => {
                  if (!mobile && !reducedMotion) interacting.current = true;
                }}
              >
                <MarkedPaper
                  reviewed={review === "award"}
                  onSelect={(value) => {
                    setQuestion(value);
                    if (!mobile && !reducedMotion) selectStep("marked");
                  }}
                />
                <div className="brand-explanation">
                  <span className="brand-label">
                    TAP A QUESTION ON THE PAPER
                  </span>
                  <Tabs
                    value={question}
                    onValueChange={(v) => {
                      setQuestion(v as QuestionKey);
                      if (!mobile && !reducedMotion) selectStep("marked");
                    }}
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
                            {question === "c" && review === "award"
                              ? "2 / 2"
                              : selected.score}
                          </strong>
                        </div>
                        <div className="brand-mark-rows">
                          {selected.rows.map(([code, text, result], i) => (
                            <div
                              key={i}
                              style={{ "--mark-index": i } as CSSProperties}
                            >
                              <b>{code}</b>
                              <span>{text}</span>
                              <small
                                className={
                                  result === "AWARDED"
                                    ? "brand-correct"
                                    : "brand-wrong"
                                }
                              >
                                {question === "c" &&
                                i === 1 &&
                                review === "award"
                                  ? "AWARDED"
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
                        {question === "c" && (
                          <div className="brand-review">
                            <h4>Teacher review.</h4>
                            <p>
                              The unit looks like m/s, but the ² may be faint.
                              Held for teacher review before it counts.
                            </p>
                            <ToggleGroup
                              type="single"
                              value={review}
                              onValueChange={(v) => {
                                if (v) {
                                  setReview(v);
                                  if (!mobile && !reducedMotion)
                                    selectStep("marked");
                                }
                              }}
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
                              Illustration:{" "}
                              {review === "award" ? "A1 awarded" : "A0 kept"}
                            </p>
                          </div>
                        )}
                      </TabsPanel>
                    ))}
                  </Tabs>
                </div>
              </div>
            </WalkthroughPanel>
            <WalkthroughPanel
              value="insights"
              flow={mobile}
              active={reducedMotion || seen.includes("insights")}
            >
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
                    Next: units drill · 10 questions{" "}
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
            </WalkthroughPanel>
          </div>
        </Tabs>
      </div>
    </section>
  );
}
