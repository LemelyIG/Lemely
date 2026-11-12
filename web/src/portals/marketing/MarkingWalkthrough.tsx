/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { ForwardArrow } from '@/components/ui/inline-arrow'
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useSceneMotion } from "./useSceneMotion";
import { MobileHow } from "./MobileHow";
import "./walkthrough-motion.css";
import "./walkthrough-tablet.css";
import { Check } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsPanel } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

const steps = [
  {
    value: "upload",
    n: "01",
    title: "Upload",
    label: "01 Upload",
    description:
      "Photograph a hand-written past paper or drop in a scan. Lemely reads every answer, working included.",
  },
  {
    value: "marked",
    n: "02",
    title: "Marked",
    label: "02 Marked",
    description:
      "Method and accuracy marks are awarded line by line against the official mark scheme, each with a confidence score.",
  },
  {
    value: "insights",
    n: "03",
    title: "Insights",
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

type Stage = "upload" | "marked" | "insights";
type Line = {
  text: string;
  mark: string;
  right: boolean;
  /** write-on delay and duration, then the mark draw delay (seconds). */
  at: [number, number, number];
};

function PaperQuestion({
  id,
  prompt,
  points,
  lines,
  marked,
  selected,
  onSelect,
}: {
  id: QuestionKey;
  prompt: string;
  points: number;
  lines: Line[];
  marked: boolean;
  selected: boolean;
  onSelect?: (question: QuestionKey) => void;
}) {
  return (
    <div className="wt-q" data-selected={selected}>
      <div className="wt-q-head">
        <span>
          <Button
            variant="ghost"
            className="walkthrough-paper-question"
            onClick={() => onSelect?.(id)}
            disabled={!marked}
            aria-label={`Explain Q3(${id})`}
            aria-pressed={selected}
          >
            ({id})
          </Button>{" "}
          {prompt}
        </span>
        <span className="wt-points">[{points}]</span>
      </div>
      {lines.map((line) => (
        <div className="wt-line" key={line.text}>
          <span
            className="wt-write"
            style={
              {
                "--d": `${line.at[0]}s`,
                "--t": `${line.at[1]}s`,
              } as CSSProperties
            }
          >
            {line.text}
          </span>
          {marked && (
            <>
              <svg
                className="wt-tick"
                width="22"
                height="18"
                viewBox="0 0 22 18"
                aria-hidden="true"
                style={{ "--d": `${line.at[2]}s` } as CSSProperties}
              >
                <path
                  d={
                    line.right
                      ? "M2 9 L8 15 L20 2"
                      : "M4 2 L18 16 M18 2 L4 16"
                  }
                  pathLength={1}
                />
              </svg>
              <span className="wt-mark">{line.mark}</span>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function MarkedPaper({
  stage,
  reviewed,
  question,
  onSelect,
}: {
  stage: Stage;
  reviewed: boolean;
  question: QuestionKey;
  onSelect?: (question: QuestionKey) => void;
}) {
  const marked = stage !== "upload";
  const pick = (id: QuestionKey) => marked && question === id;
  return (
    <div className="wt-paper brand-script" data-stage={stage}>
      {stage === "upload" && <span className="walkthrough-scan" aria-hidden="true" />}
      <div className="wt-paper-head">
        <span className="brand-label">PHYSICS · PAPER 4 · QUESTION 3</span>
        {marked && (
          <span className="wt-score">
            <svg width="70" height="44" viewBox="0 0 70 44" aria-hidden="true">
              <ellipse cx="35" cy="22" rx="33" ry="19" pathLength={1} />
            </svg>
            {reviewed ? "5" : "4"}/6
          </span>
        )}
      </div>
      <p className="wt-stem">A cyclist travels 1.2 km in 4.0 minutes.</p>
      <PaperQuestion
        id="a"
        prompt="Calculate the average speed in m/s."
        points={3}
        marked={marked}
        selected={pick("a")}
        onSelect={onSelect}
        lines={[
          { text: "v = d / t", mark: "M1", right: true, at: [0.1, 0.4, 0.05] },
          { text: "= 1200 / 240", mark: "M1", right: true, at: [0.35, 0.45, 0.12] },
          { text: "= 5", mark: "A0", right: false, at: [0.6, 0.25, 0.19] },
        ]}
      />
      <PaperQuestion
        id="b"
        prompt="State one difference between speed and velocity."
        points={1}
        marked={marked}
        selected={pick("b")}
        onSelect={onSelect}
        lines={[
          {
            text: "velocity has a direction",
            mark: "B1",
            right: true,
            at: [0.8, 0.5, 0.26],
          },
        ]}
      />
      <PaperQuestion
        id="c"
        prompt="It accelerates from rest to 5.0 m/s in 10 s. Calculate the acceleration."
        points={2}
        marked={marked}
        selected={pick("c")}
        onSelect={onSelect}
        lines={[
          {
            text: "a = v / t = 5 / 10",
            mark: "M1",
            right: true,
            at: [1.05, 0.45, 0.33],
          },
          {
            text: "= 0.5 m/s",
            mark: reviewed ? "A1" : "A0",
            right: reviewed,
            at: [1.3, 0.3, 0.4],
          },
        ]}
      />
    </div>
  );
}

// Step bands run from the moment the wrap pins (progress 0) to the moment it releases (1). Step 1 owns the
// first quarter (about 21vh of an 85vh pin) so the scene responds soon after it locks; tab clicks land
// inside each band.
const STEP_BANDS = [0.25, 0.62] as const;
const STEP_TARGET: Record<string, number> = {
  upload: 0.1,
  marked: 0.45,
  insights: 0.82,
};
const stepAt = (progress: number) =>
  progress < STEP_BANDS[0]
    ? "upload"
    : progress < STEP_BANDS[1]
      ? "marked"
      : "insights";
function pinGeometry(section: HTMLElement) {
  const wrap = section.firstElementChild as HTMLElement;
  return {
    top: parseFloat(getComputedStyle(wrap).top) || 64,
    range: Math.max(1, section.offsetHeight - wrap.offsetHeight),
  };
}
function pinProgress(section: HTMLElement) {
  const { top, range } = pinGeometry(section);
  return Math.max(
    0,
    Math.min(1, (top - section.getBoundingClientRect().top) / range),
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

/** Tablet widths cannot pin a 1180px scene at a readable size, so they get the real-size reflow in walkthrough-tablet.css. */
const TABLET = "(min-width: 760px) and (max-width: 1099px)";

export function MarkingWalkthrough() {
  const [tablet, setTablet] = useState(() => window.matchMedia(TABLET).matches);
  // Without a scroll scene the visitor lands on the step that carries the claim.
  const [step, setStep] = useState(() => (tablet ? "marked" : "upload"));
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
  // The reference starts the one-shot write-on at page load, long before the visitor reaches the pinned scene,
  // so it is already finished on arrival while only the scan beam keeps sweeping. Latch once.
  const [primed, setPrimed] = useState(false);

  useEffect(() => {
    setPrimed(true);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 759px)");
    const change = () => setMobile(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);

  useEffect(() => {
    const media = window.matchMedia(TABLET);
    const change = () => setTablet(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  // No pin, no scale: the scene flows in the page and the tabs drive the step.
  const unpinned = reducedMotion || tablet;

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
    // Scroll position, not visibility, decides the step: the reference recomputes it on every
    // scroll, so leaving and re-entering the section must land on the step for that position.
    if (unpinned) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const bounds = element.getBoundingClientRect();
      if (bounds.bottom <= 0 || bounds.top >= window.innerHeight)
        interacting.current = false;
      const progress = pinProgress(element);
      if (fill.current) fill.current.style.transform = `scaleX(${progress.toFixed(3)})`;
      if (!interacting.current) setStep(stepAt(progress));
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
        !event.target.closest(".brand-stage")
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
  }, [unpinned, mobile, pageVisible, ref]);

  useEffect(() => {
    const grid = ref.current?.querySelector<HTMLElement>(".brand-walkthrough");
    if (!grid || mobile || unpinned) return;
    const host = grid.parentElement;
    let fitK = 1;
    const fit = () => {
      // Same fit as the reference: the 1180px scene shrinks to the sticky host's height and width.
      const availW = (host?.clientWidth ?? window.innerWidth) - 64;
      const k = Math.min(
        1,
        (window.innerHeight - 96) / Math.max(1, grid.offsetHeight),
        availW / 1180,
      );
      // Reference hysteresis: ignore sub-0.5% changes so a 1176px host does not nudge a 1:1 scene.
      if (Math.abs(fitK - k) > 0.005) {
        fitK = k;
        grid.style.setProperty("--walkthrough-scale", k.toFixed(3));
      }
    };
    const observer = new ResizeObserver(fit);
    observer.observe(grid);
    if (host) observer.observe(host);
    window.addEventListener("resize", fit);
    fit();
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", fit);
      grid.style.removeProperty("--walkthrough-scale");
    };
  }, [mobile, unpinned, ref]);

  const selectStep = (value: string) => {
    setStep(value);
    if (mobile || unpinned || !ref.current) return;
    const bounds = ref.current.getBoundingClientRect();
    const { top, range } = pinGeometry(ref.current);
    window.scrollTo({
      top: window.scrollY + bounds.top - top + range * STEP_TARGET[value],
      behavior: "instant",
    });
  };
  const [question, setQuestion] = useState<QuestionKey>("a");
  const [review, setReview] = useState("keep");
  const selected = questions[question];
  if (mobile) return <MobileHow />;
  const stage = step as Stage;
  const stepIndex = steps.findIndex((x) => x.value === step);
  const holdMarked = () => {
    if (!mobile && !unpinned && step === "marked")
      interacting.current = true;
  };
  return (
    <section
      id="how"
      ref={ref}
      className="brand-how brand-section walkthrough-motion"
      data-motion={enabled}
      data-primed={primed && pageVisible}
      data-reduced={reducedMotion}
      data-tablet={tablet}
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
            <span className="brand-label">
              {tablet ? "HOW IT WORKS" : "HOW IT WORKS · SCROLL"}
            </span>
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
              <TabsList
                className="walkthrough-steps"
                label="Marking walkthrough"
                tabs={steps.map((x, i) => ({
                  value: x.value,
                  label: (
                    <>
                      <span className="wt-badge" data-reached={i <= stepIndex}>
                        {x.n}
                      </span>{" "}
                      <span className="wt-step-copy">
                        <span className="wt-step-title">{x.title}</span>{" "}
                        <span className="wt-step-desc">{x.description}</span>
                      </span>
                    </>
                  ),
                }))}
              />
            </div>
          </div>
          <div
            className="brand-stage"
            onPointerDownCapture={holdMarked}
            onFocusCapture={holdMarked}
          >
            <MarkedPaper
              stage={stage}
              reviewed={review === "award"}
              question={question}
              onSelect={(value) => {
                setQuestion(value);
                if (!mobile && !unpinned && step === "marked")
                  selectStep("marked");
              }}
            />
            <div className="wt-col">
              <WalkthroughPanel
                value="upload"
                flow={mobile}
                active={reducedMotion || seen.includes("upload")}
              >
                <div className="wt-card wt-upload">
                  <h3>Uploading 3 photos</h3>
                  <div
                    className="walkthrough-upload-progress"
                    aria-hidden="true"
                  >
                    <span />
                  </div>
                  <ul className="wt-checks">
                    <li style={{ "--d": "0.1s" } as CSSProperties}>
                      <span className="wt-dot wt-dot-ok" aria-hidden="true">
                        <Check weight="bold" />
                      </span>
                      3 pages received
                    </li>
                    <li style={{ "--d": "0.18s" } as CSSProperties}>
                      <span className="wt-dot wt-dot-ok" aria-hidden="true">
                        <Check weight="bold" />
                      </span>
                      Handwriting read · 6 answers
                    </li>
                    <li style={{ "--d": "0.26s" } as CSSProperties}>
                      <span className="wt-dot wt-dot-wait" aria-hidden="true" />
                      Matching to the 0625 mark scheme…
                    </li>
                  </ul>
                </div>
                <p className="wt-aside">
                  Any phone camera. Crooked pages, pencil and crossings-out are
                  fine.
                </p>
              </WalkthroughPanel>
              <WalkthroughPanel
                value="marked"
                flow={mobile}
                active={reducedMotion || seen.includes("marked")}
              >
                <span className="brand-label wt-tap">
                  TAP A QUESTION ON THE PAPER
                </span>
                <div className="wt-card wt-explain">
                  <div className="wt-explain-title">
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
                    {selected.rows.map(([code, text, result], i) => {
                      const awarded =
                        result === "AWARDED" ||
                        (question === "c" && i === 1 && review === "award");
                      return (
                        <div
                          key={`${question}-${i}`}
                          style={{ "--mark-index": i } as CSSProperties}
                        >
                          <b>{code}</b>
                          <span>{text}</span>
                          <small
                            className={
                              awarded
                                ? "brand-correct"
                                : result === "CHECK"
                                  ? "brand-check"
                                  : "brand-wrong"
                            }
                          >
                            {awarded ? "AWARDED" : result}
                          </small>
                        </div>
                      );
                    })}
                  </div>
                  <div className="wt-confidence">
                    <p className="brand-confidence">
                      <span>AI confidence</span>{" "}
                      <span>{selected.confidence}%</span>
                    </p>
                    <div className="brand-confidence-track">
                      <span
                        data-low={selected.confidence < 80}
                        style={{ width: `${selected.confidence}%` }}
                      />
                    </div>
                  </div>
                  <aside className="brand-scheme">
                    <span className="brand-label">
                      MARK SCHEME · 0625 · {selected.label}
                    </span>
                    <p>{selected.scheme}</p>
                  </aside>
                  {question === "c" && (
                    <div className="brand-review">
                      <p>
                        <b>Teacher review.</b> The unit looks like m/s, but the
                        ² may be faint. Sent to your queue before it
                        counts.
                      </p>
                      <ToggleGroup
                        type="single"
                        value={review}
                        onValueChange={(v) => {
                          if (v) {
                            setReview(v);
                            if (!mobile && !unpinned)
                              selectStep("marked");
                          }
                        }}
                        aria-label="Teacher review"
                      >
                        <ToggleGroupItem value="keep">Keep A0</ToggleGroupItem>
                        <ToggleGroupItem value="award">
                          Award A1
                        </ToggleGroupItem>
                      </ToggleGroup>
                    </div>
                  )}
                </div>
              </WalkthroughPanel>
              <WalkthroughPanel
                value="insights"
                flow={mobile}
                active={reducedMotion || seen.includes("insights")}
              >
                <div className="wt-card wt-insights">
                  <div className="wt-insights-head">
                    <h3>Weak topic found</h3>
                    <span className="brand-label">ACROSS 3 PAPERS</span>
                  </div>
                  <div className="wt-weak">
                    <strong>Units &amp; SI</strong>
                    <div className="brand-topic-list">
                      <span style={{ "--dx": "-160px", "--dy": "-120px", "--r": "-14deg", "--d": "0.05s" } as CSSProperties}>
                        P4 Q3(a) <b>−1</b>
                      </span>
                      <span style={{ "--dx": "-120px", "--dy": "-30px", "--r": "10deg", "--d": "0.12s" } as CSSProperties}>
                        P4 Q3(c) <b>−1</b>
                      </span>
                      <span style={{ "--dx": "80px", "--dy": "90px", "--r": "-8deg", "--d": "0.19s" } as CSSProperties}>
                        P2 Q5 <b>−2</b>
                      </span>
                    </div>
                  </div>
                  <div className="wt-grade brand-grade-transition">
                    <span>Predicted grade</span>
                    <b className="wt-grade-b">B</b>
                    <span className="wt-arrow" aria-hidden="true"><ForwardArrow /></span>
                    <b className="wt-grade-a">A</b>
                  </div>
                  <div className="wt-next">
                    <span>Next: units drill · 10 questions</span>
                    <span className="wt-next-time">15 MIN</span>
                  </div>
                  <p className="wt-report brand-report">
                    Progress report ready to send to Layan's parents.
                  </p>
                </div>
              </WalkthroughPanel>
            </div>
          </div>
        </Tabs>
      </div>
    </section>
  );
}
