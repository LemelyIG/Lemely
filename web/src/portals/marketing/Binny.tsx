/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
export type BinnyMood =
  "idle" | "thinking" | "open" | "happy" | "wink" | "nerd";

/** The supplied mascot's FAQ expressions, shared with the closing cameo. */
export function Binny({
  mood = "open",
  className = "",
  compact = false,
}: {
  mood?: BinnyMood;
  className?: string;
  /** Head-and-shoulders crop (reference viewBox 30 10 140 140) for small icon use. */
  compact?: boolean;
}) {
  const happy = mood === "happy";
  return (
    <svg
      className={className}
      data-mood={mood}
      aria-hidden="true"
      width="200"
      height="220"
      viewBox={compact ? "30 10 140 140" : "0 0 200 220"}
      overflow={compact ? "visible" : undefined}
    >
      <g
        className="brand-binny-ear brand-binny-ear-left"
        transform={compact ? "rotate(-6 75 100)" : undefined}
      >
        <path
          d="M66 102 L62 40 Q62 16 75 16 Q88 16 88 40 L84 102"
          fill="none"
          stroke="var(--brand-art-16)"
          strokeWidth="8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <g
        className="brand-binny-ear brand-binny-ear-right"
        transform={compact ? "rotate(6 125 100)" : undefined}
      >
        <path
          d="M116 102 L112 40 Q112 16 125 16 Q138 16 138 40 L134 102"
          fill="none"
          stroke="var(--brand-art-16)"
          strokeWidth="8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <path
        d={
          compact
            ? "M40 104 H160 L154 150 H46 Z"
            : "M40 104 H160 L152 186 Q151 196 141 196 H59 Q49 196 48 186 Z"
        }
        fill="var(--brand-abyss)"
      />
      <rect
        x="34"
        y="94"
        width="132"
        height="18"
        rx="8"
        fill="var(--brand-art-17)"
      />
      {!compact && (
        <>
          <ellipse
            cx="62"
            cy="160"
            rx="9"
            ry="5.5"
            opacity=".55"
            fill="var(--brand-art-18)"
          />
          <ellipse
            cx="138"
            cy="160"
            rx="9"
            ry="5.5"
            opacity=".55"
            fill="var(--brand-art-18)"
          />
        </>
      )}
      <g transform={compact ? "translate(0 -8)" : undefined}>
        {mood === "nerd" ? (
          <g fill="none" stroke="var(--brand-tide)" strokeWidth="5">
            <circle cx="78" cy="140" r="17" />
            <circle cx="122" cy="140" r="17" />
            <path d="M95 138 Q100 134 105 138" />
          </g>
        ) : (
          <g className="brand-binny-eyes">
            {happy ? (
              <path
                d="M68 143 Q78 130 88 143"
                fill="none"
                stroke="var(--brand-white)"
                strokeWidth="6"
                strokeLinecap="round"
              />
            ) : (
              <>
                <ellipse
                  cx="78"
                  cy="140"
                  rx="11"
                  ry="12"
                  fill="var(--brand-white)"
                />
                <circle
                  cx={mood === "thinking" ? 84 : 80}
                  cy="141"
                  r="6.5"
                  fill="var(--brand-ink)"
                />
              </>
            )}
            {happy || mood === "wink" ? (
              <path
                d="M112 143 Q122 130 132 143"
                fill="none"
                stroke="var(--brand-white)"
                strokeWidth="6"
                strokeLinecap="round"
              />
            ) : (
              <>
                <ellipse
                  cx="122"
                  cy="140"
                  rx="11"
                  ry="12"
                  fill="var(--brand-white)"
                />
                <circle
                  cx={mood === "thinking" ? 128 : 124}
                  cy="141"
                  r="6.5"
                  fill="var(--brand-ink)"
                />
              </>
            )}
          </g>
        )}
      </g>
      {!compact &&
        (mood === "open" ? (
          <path
            d="M86 160 H114 Q113 180 100 180 Q87 180 86 160Z"
            fill="var(--brand-ink)"
            stroke="var(--brand-white)"
            strokeWidth="3"
            strokeLinejoin="round"
          />
        ) : (
          <path
            d={
              mood === "thinking" ? "M92 167 H108" : "M90 163 Q100 172 110 163"
            }
            fill="none"
            stroke="var(--brand-white)"
            strokeWidth="4.5"
            strokeLinecap="round"
          />
        ))}
    </svg>
  );
}

/** The closing cameo: head and shoulders only, one eye open and one winking, cropped by the section edge. */
export function BinnyPeek() {
  return (
    <svg
      className="brand-closing-binny"
      aria-hidden="true"
      width="170"
      height="150"
      viewBox="20 0 160 150"
    >
      <g className="brand-binny-ear brand-binny-ear-left">
        <path
          d="M66 102 L62 40 Q62 16 75 16 Q88 16 88 40 L84 102"
          fill="none"
          stroke="var(--brand-art-16)"
          strokeWidth="7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <g className="brand-binny-ear brand-binny-ear-right">
        <path
          d="M116 102 L112 40 Q112 16 125 16 Q138 16 138 40 L134 102"
          fill="none"
          stroke="var(--brand-art-16)"
          strokeWidth="7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <path d="M40 104 H160 L156 160 H44 Z" fill="var(--brand-abyss)" />
      <rect
        x="34"
        y="94"
        width="132"
        height="18"
        rx="8"
        fill="var(--brand-art-17)"
      />
      <ellipse
        cx="62"
        cy="142"
        rx="9"
        ry="5.5"
        opacity=".55"
        fill="var(--brand-art-18)"
      />
      <ellipse
        cx="138"
        cy="142"
        rx="9"
        ry="5.5"
        opacity=".55"
        fill="var(--brand-art-18)"
      />
      <ellipse cx="78" cy="132" rx="11" ry="12" fill="var(--brand-white)" />
      <circle cx="80" cy="133" r="6.5" fill="var(--brand-ink)" />
      <circle cx="82.5" cy="130" r="2.2" fill="var(--brand-white)" />
      <path
        d="M112 135 Q122 122 132 135"
        fill="none"
        stroke="var(--brand-white)"
        strokeWidth="5"
        strokeLinecap="round"
      />
    </svg>
  );
}
