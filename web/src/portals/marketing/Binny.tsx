/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
export type BinnyMood = 'idle' | 'thinking' | 'open' | 'happy' | 'wink' | 'nerd'

/** The supplied mascot's FAQ expressions, shared with the closing cameo. */
export function Binny({
  mood = 'idle',
  active = false,
  className = '',
}: {
  mood?: BinnyMood
  active?: boolean
  className?: string
}) {
  const happy = mood === 'happy'
  return (
    <svg
      className={className}
      data-mood={mood}
      data-motion={active ? 'active' : 'still'}
      aria-hidden="true"
      width="200"
      height="220"
      viewBox="0 0 200 220"
    >
      <g className="brand-binny-ear brand-binny-ear-left">
        <path
          d="M66 102 L62 40 Q62 16 75 16 Q88 16 88 40 L84 102"
          fill="none"
          stroke="var(--brand-art-16)"
          strokeWidth="8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <g className="brand-binny-ear brand-binny-ear-right">
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
        d="M40 104 H160 L152 186 Q151 196 141 196 H59 Q49 196 48 186 Z"
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
      <g className="brand-binny-eyes">
        {happy ? (
          <path
            d="M68 143 Q78 130 88 143"
            fill="none"
            stroke="var(--brand-white)"
            strokeWidth="5"
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
              cx={mood === 'thinking' ? 82 : 78}
              cy={mood === 'thinking' ? 137 : 141}
              r="6.5"
              fill="var(--brand-ink)"
            />
          </>
        )}
        {happy || mood === 'wink' ? (
          <path
            d="M112 143 Q122 130 132 143"
            fill="none"
            stroke="var(--brand-white)"
            strokeWidth="5"
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
              cx={mood === 'thinking' ? 126 : 122}
              cy={mood === 'thinking' ? 137 : 141}
              r="6.5"
              fill="var(--brand-ink)"
            />
          </>
        )}
      </g>
      {mood === 'nerd' && (
        <g fill="none" stroke="var(--brand-tide)" strokeWidth="5">
          <circle cx="78" cy="140" r="17" />
          <circle cx="122" cy="140" r="17" />
          <path d="M95 138 Q100 134 105 138" />
        </g>
      )}
      {mood === 'open' ? (
        <path
          d="M86 160 H114 Q113 180 100 180 Q87 180 86 160Z"
          fill="var(--brand-ink)"
          stroke="var(--brand-white)"
          strokeWidth="3"
          strokeLinejoin="round"
        />
      ) : (
        <path
          d={mood === 'thinking' ? 'M92 167 H108' : 'M90 163 Q100 172 110 163'}
          fill="none"
          stroke="var(--brand-white)"
          strokeWidth="4.5"
          strokeLinecap="round"
        />
      )}
    </svg>
  )
}
