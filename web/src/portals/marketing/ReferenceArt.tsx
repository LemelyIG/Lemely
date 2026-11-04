/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
/* Supplied workshop artwork, with original geometry and semantic tokens. */
export function HeroChartArt() {
  return (
    <svg
      viewBox="0 0 640 400"
      style={{
        width: '100%',
        height: 'auto',
        display: 'block',
        overflow: 'visible',
      }}
    >
      <defs>
        <linearGradient id="hcArea" x1="0" y1="0" x2="0" y2="1">
          <stop
            offset="0"
            stopColor="var(--brand-art-1)"
            stopOpacity="0.9"
          ></stop>
          <stop
            offset="1"
            stopColor="var(--brand-art-2)"
            stopOpacity="0"
          ></stop>
        </linearGradient>
        <clipPath id="hcClip">
          <rect data-hc="clip" x="0" y="0" width="640" height="400"></rect>
        </clipPath>
      </defs>
      <g fontFamily="var(--brand-mono)" fontSize="13" fill="var(--brand-art-3)">
        <line
          x1="56"
          y1="90"
          x2="616"
          y2="90"
          stroke="var(--brand-art-4)"
          strokeWidth="1.5"
          strokeDasharray="4 6"
        ></line>
        <text x="20" y="95">
          {'A*'}
        </text>
        <line
          x1="56"
          y1="170"
          x2="616"
          y2="170"
          stroke="var(--brand-art-4)"
          strokeWidth="1.5"
          strokeDasharray="4 6"
        ></line>
        <text x="26" y="175">
          {'A'}
        </text>
        <line
          x1="56"
          y1="250"
          x2="616"
          y2="250"
          stroke="var(--brand-art-4)"
          strokeWidth="1.5"
          strokeDasharray="4 6"
        ></line>
        <text x="26" y="255">
          {'B'}
        </text>
        <line
          x1="56"
          y1="320"
          x2="616"
          y2="320"
          stroke="var(--brand-art-4)"
          strokeWidth="1.5"
          strokeDasharray="4 6"
        ></line>
        <text x="26" y="325">
          {'C'}
        </text>
        <text x="68" y="386">
          {'Paper 1'}
        </text>
        <text x="188" y="386">
          {'Paper 2'}
        </text>
        <text x="308" y="386">
          {'Paper 3'}
        </text>
        <text x="428" y="386">
          {'Paper 4'}
        </text>
        <text x="548" y="386">
          {'Paper 5'}
        </text>
      </g>
      <g>
        <path
          d="M90 320 L210 250 L330 250 L450 170 L570 90 L570 360 L90 360 Z"
          fill="url(#hcArea)"
          clipPath="url(#hcClip)"
        ></path>
        <path
          d="M90 320 L210 250 L330 250 L450 170 L570 90"
          fill="none"
          stroke="var(--brand-art-5)"
          strokeWidth="4.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          clipPath="url(#hcClip)"
        ></path>
        <g data-hc="pt" transform="translate(90 320) scale(1)">
          <circle
            r="9"
            fill="var(--brand-art-6)"
            stroke="var(--brand-art-5)"
            strokeWidth="4"
          ></circle>
          <rect
            x="12"
            y="10"
            width="30"
            height="24"
            rx="7"
            fill="var(--brand-art-7)"
          ></rect>
          <text
            x="27"
            y="27"
            textAnchor="middle"
            fontFamily="var(--brand-display)"
            fontWeight="800"
            fontSize="15"
            fill="var(--brand-art-6)"
          >
            {'C'}
          </text>
        </g>
        <g data-hc="pt" transform="translate(210 250) scale(1)">
          <circle
            r="9"
            fill="var(--brand-art-6)"
            stroke="var(--brand-art-5)"
            strokeWidth="4"
          ></circle>
          <rect
            x="12"
            y="10"
            width="30"
            height="24"
            rx="7"
            fill="var(--brand-art-8)"
          ></rect>
          <text
            x="27"
            y="27"
            textAnchor="middle"
            fontFamily="var(--brand-display)"
            fontWeight="800"
            fontSize="15"
            fill="var(--brand-art-6)"
          >
            {'B'}
          </text>
        </g>
        <g data-hc="pt" transform="translate(330 250) scale(1)">
          <circle
            r="9"
            fill="var(--brand-art-6)"
            stroke="var(--brand-art-5)"
            strokeWidth="4"
          ></circle>
          <rect
            x="12"
            y="10"
            width="30"
            height="24"
            rx="7"
            fill="var(--brand-art-8)"
          ></rect>
          <text
            x="27"
            y="27"
            textAnchor="middle"
            fontFamily="var(--brand-display)"
            fontWeight="800"
            fontSize="15"
            fill="var(--brand-art-6)"
          >
            {'B'}
          </text>
        </g>
        <g data-hc="pt" transform="translate(450 170) scale(1)">
          <circle
            r="9"
            fill="var(--brand-art-6)"
            stroke="var(--brand-art-5)"
            strokeWidth="4"
          ></circle>
          <rect
            x="12"
            y="10"
            width="30"
            height="24"
            rx="7"
            fill="var(--brand-art-9)"
          ></rect>
          <text
            x="27"
            y="27"
            textAnchor="middle"
            fontFamily="var(--brand-display)"
            fontWeight="800"
            fontSize="15"
            fill="var(--brand-art-6)"
          >
            {'A'}
          </text>
        </g>
        <g data-hc="pt" transform="translate(570 90) scale(1)">
          <circle
            r="9"
            fill="var(--brand-art-6)"
            stroke="var(--brand-art-5)"
            strokeWidth="4"
          ></circle>
          <rect
            x="12"
            y="10"
            width="36"
            height="24"
            rx="7"
            fill="var(--brand-art-10)"
          ></rect>
          <text
            x="30"
            y="27"
            textAnchor="middle"
            fontFamily="var(--brand-display)"
            fontWeight="800"
            fontSize="15"
            fill="var(--brand-art-6)"
          >
            {'A*'}
          </text>
        </g>
        <g data-hc="spark" transform="translate(570 40)" opacity="1">
          <path
            d="M0 -22 Q0 0 22 0 Q0 0 0 22 Q0 0 -22 0 Q0 0 0 -22Z"
            fill="var(--brand-art-11)"
          ></path>
          <path
            d="M40 10 Q40 20 50 20 Q40 20 40 30 Q40 20 30 20 Q40 20 40 10Z"
            fill="var(--brand-art-12)"
          ></path>
          <path
            d="M-38 18 Q-38 26 -30 26 Q-38 26 -38 34 Q-38 26 -46 26 Q-38 26 -38 18Z"
            fill="var(--brand-art-11)"
          ></path>
        </g>
        <g data-hc="binny" transform="translate(528 0)" role="button" tabIndex={0} aria-label="Celebrate with Binny">
          <g data-hc="lvl" opacity="0" style={{ pointerEvents: 'none' }}>
            <g transform="translate(42 -14)">
              <path
                d="M-18 8 L-20 -10 L-9 -2 L0 -15 L9 -2 L20 -10 L18 8Z"
                fill="var(--brand-art-11)"
                stroke="var(--brand-art-13)"
                strokeWidth="1.5"
                strokeLinejoin="round"
              ></path>
            </g>
            <g transform="translate(42 -40)">
              <rect
                x="-44"
                y="-15"
                width="88"
                height="26"
                rx="13"
                fill="var(--brand-art-5)"
              ></rect>
              <text
                x="0"
                y="3"
                textAnchor="middle"
                fontFamily="var(--brand-mono)"
                fontWeight="600"
                fontSize="12"
                fill="var(--brand-art-6)"
              >
                {'LEVEL UP +50'}
              </text>
            </g>
          </g>
          <g data-hc="squash">
            <g transform="scale(0.42)">
              <rect
                x="54"
                y="168"
                width="92"
                height="48"
                rx="4"
                fill="var(--brand-art-6)"
                stroke="var(--brand-art-14)"
                strokeWidth="2"
                transform="rotate(-3 100 192)"
              ></rect>
              <path
                d="M66 198 H112 M66 206 H100"
                stroke="var(--brand-art-15)"
                strokeWidth="3"
                strokeLinecap="round"
                transform="rotate(-3 100 192)"
              ></path>
              <g data-hc="earL" transform="rotate(-6 75 100)">
                <path
                  d="M66 102 L62 40 Q62 16 75 16 Q88 16 88 40 L84 102"
                  fill="none"
                  stroke="var(--brand-art-16)"
                  strokeWidth="7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                ></path>
                <path
                  d="M65 92 L63 44"
                  stroke="var(--brand-art-6)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  opacity="0.7"
                ></path>
              </g>
              <g data-hc="earR" transform="rotate(6 125 100)">
                <path
                  d="M116 102 L112 40 Q112 16 125 16 Q138 16 138 40 L134 102"
                  fill="none"
                  stroke="var(--brand-art-16)"
                  strokeWidth="7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                ></path>
                <path
                  d="M115 92 L113 44"
                  stroke="var(--brand-art-6)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  opacity="0.7"
                ></path>
              </g>
              <path
                d="M40 104 H160 L152 186 Q151 196 141 196 H59 Q49 196 48 186 Z"
                fill="var(--brand-art-5)"
              ></path>
              <rect
                x="34"
                y="94"
                width="132"
                height="18"
                rx="8"
                fill="var(--brand-art-17)"
              ></rect>
              <path
                d="M42 100 H158"
                stroke="var(--brand-art-6)"
                strokeWidth="2"
                opacity="0.18"
                strokeLinecap="round"
              ></path>
              <ellipse
                cx="62"
                cy="160"
                rx="9"
                ry="5.5"
                fill="var(--brand-art-18)"
                opacity="0.55"
              ></ellipse>
              <ellipse
                cx="138"
                cy="160"
                rx="9"
                ry="5.5"
                fill="var(--brand-art-18)"
                opacity="0.55"
              ></ellipse>
              <g data-hc="eyes">
                <ellipse
                  cx="78"
                  cy="140"
                  rx="11"
                  ry="12"
                  fill="var(--brand-art-6)"
                ></ellipse>
                <ellipse
                  cx="122"
                  cy="140"
                  rx="11"
                  ry="12"
                  fill="var(--brand-art-6)"
                ></ellipse>
                <g data-hc="pupils">
                  <circle
                    cx="78"
                    cy="141"
                    r="6.5"
                    fill="var(--brand-art-19)"
                  ></circle>
                  <circle
                    cx="80.5"
                    cy="138"
                    r="2.2"
                    fill="var(--brand-art-6)"
                  ></circle>
                  <circle
                    cx="122"
                    cy="141"
                    r="6.5"
                    fill="var(--brand-art-19)"
                  ></circle>
                  <circle
                    cx="124.5"
                    cy="138"
                    r="2.2"
                    fill="var(--brand-art-6)"
                  ></circle>
                </g>
              </g>
              <g data-hc="happy" style={{ display: 'none' }}>
                <path
                  d="M68 143 Q78 130 88 143"
                  fill="none"
                  stroke="var(--brand-art-6)"
                  strokeWidth="5"
                  strokeLinecap="round"
                ></path>
                <path
                  d="M112 143 Q122 130 132 143"
                  fill="none"
                  stroke="var(--brand-art-6)"
                  strokeWidth="5"
                  strokeLinecap="round"
                ></path>
              </g>
              <path
                data-hc="smile" d="M90 163 Q100 172 110 163"
                fill="none"
                stroke="var(--brand-art-6)"
                strokeWidth="4.5"
                strokeLinecap="round"
              ></path>
              <g data-hc="open" style={{ display: 'none' }}>
                <path
                  d="M86 160 H114 Q113 180 100 180 Q87 180 86 160Z"
                  fill="var(--brand-art-19)"
                  stroke="var(--brand-art-6)"
                  strokeWidth="3"
                  strokeLinejoin="round"
                ></path>
                <path
                  d="M93 174 Q100 168 107 174 Q104 179 100 179 Q96 179 93 174Z"
                  fill="var(--brand-art-18)"
                ></path>
              </g>
            </g>
          </g>
        </g>
      </g>
    </svg>
  )
}
export type FeatureArtKey =
  | 'marking'
  | 'confidence'
  | 'predicted'
  | 'clusters'
  | 'trends'
  | 'plan'
  | 'xp'
  | 'content'
export function FeatureArt({ name }: { name: FeatureArtKey }) {
  switch (name) {
    case 'marking':
      return (
        <div className="brand-art">
          <div
            style={{
              width: '100%',
              maxWidth: '440px',
              background: 'var(--brand-art-6)',
              borderRadius: '16px',
              padding: '20px 22px',
              boxShadow:
                '0 1px 0 var(--brand-art-20),0 18px 40px -24px var(--brand-art-21)',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--brand-mono)',
                fontSize: '11px',
                letterSpacing: '0.06em',
                color: 'var(--brand-art-3)',
              }}
            >
              {'Q3(a) \u00b7 CALCULATE SPEED IN m/s \u00b7 [3]'}
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span
                style={{
                  fontFamily: 'var(--brand-hand)',
                  fontSize: '28px',
                  color: 'var(--brand-art-22)',
                  flex: '1',
                }}
              >
                {'v = d / t'}
              </span>
              <svg width="24" height="20" viewBox="0 0 24 20">
                <path
                  d="M2 10 L9 17 L22 3"
                  fill="none"
                  stroke="var(--brand-art-23)"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  pathLength="1"
                  strokeDasharray="1"
                  strokeDashoffset="0"
                  style={{}}
                ></path>
              </svg>
              <span
                style={{
                  fontFamily: 'var(--brand-hand)',
                  fontSize: '24px',
                  color: 'var(--brand-art-23)',
                  width: '36px',
                  transform: 'scale(1)',
                }}
              >
                {'M1'}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span
                style={{
                  fontFamily: 'var(--brand-hand)',
                  fontSize: '28px',
                  color: 'var(--brand-art-22)',
                  flex: '1',
                }}
              >
                {'= 1200 \u00f7 240'}
              </span>
              <svg width="24" height="20" viewBox="0 0 24 20">
                <path
                  d="M2 10 L9 17 L22 3"
                  fill="none"
                  stroke="var(--brand-art-23)"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  pathLength="1"
                  strokeDasharray="1"
                  strokeDashoffset="0"
                  style={{}}
                ></path>
              </svg>
              <span
                style={{
                  fontFamily: 'var(--brand-hand)',
                  fontSize: '24px',
                  color: 'var(--brand-art-23)',
                  width: '36px',
                  transform: 'scale(1)',
                }}
              >
                {'M1'}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span
                style={{
                  fontFamily: 'var(--brand-hand)',
                  fontSize: '28px',
                  color: 'var(--brand-art-22)',
                  flex: '1',
                }}
              >
                {'= 5'}
              </span>
              <svg width="24" height="20" viewBox="0 0 24 20">
                <path
                  d="M4 3 L20 17 M20 3 L4 17"
                  fill="none"
                  stroke="var(--brand-art-23)"
                  strokeWidth="3"
                  strokeLinecap="round"
                  pathLength="1"
                  strokeDasharray="1"
                  strokeDashoffset="0"
                  style={{}}
                ></path>
              </svg>
              <span
                style={{
                  fontFamily: 'var(--brand-hand)',
                  fontSize: '24px',
                  color: 'var(--brand-art-23)',
                  width: '36px',
                  transform: 'scale(1)',
                }}
              >
                {'A0'}
              </span>
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                background: 'var(--brand-art-24)',
                borderRadius: '10px',
                padding: '10px 12px',
                opacity: '1',
              }}
            >
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  fontWeight: '600',
                  color: 'var(--brand-art-25)',
                }}
              >
                {'MARK SCHEME \u00b7 A1'}
              </span>
              <span style={{ fontSize: '14px', color: 'var(--brand-art-19)' }}>
                {'5 m/s \u2014 unit required'}
              </span>
            </div>
          </div>
        </div>
      )
    case 'confidence':
      return (
        <div className="brand-art">
          <div
            style={{
              width: '100%',
              maxWidth: '360px',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px',
            }}
          >
            <div
              style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: '14px',
                  fontWeight: '600',
                }}
              >
                <span>{'Q3(a)'}</span>
                <span style={{ fontFamily: 'var(--brand-mono)' }}>{'96%'}</span>
              </div>
              <div
                style={{
                  height: '10px',
                  borderRadius: '5px',
                  background: 'var(--brand-art-26)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: '96%',
                    height: '100%',
                    borderRadius: '5px',
                    background: 'var(--brand-art-27)',
                    transformOrigin: 'left',
                    transform: 'scaleX(1)',
                  }}
                ></div>
              </div>
            </div>
            <div
              style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: '14px',
                  fontWeight: '600',
                }}
              >
                <span>{'Q3(b)'}</span>
                <span style={{ fontFamily: 'var(--brand-mono)' }}>{'91%'}</span>
              </div>
              <div
                style={{
                  height: '10px',
                  borderRadius: '5px',
                  background: 'var(--brand-art-26)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: '91%',
                    height: '100%',
                    borderRadius: '5px',
                    background: 'var(--brand-art-27)',
                    transformOrigin: 'left',
                    transform: 'scaleX(1)',
                  }}
                ></div>
              </div>
            </div>
            <div
              style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  fontSize: '14px',
                  fontWeight: '600',
                }}
              >
                <span
                  style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
                >
                  {'Q3(c)'}
                  <span
                    style={{
                      fontFamily: 'var(--brand-mono)',
                      fontSize: '10px',
                      letterSpacing: '0.06em',
                      background: 'var(--brand-art-28)',
                      color: 'var(--brand-art-29)',
                      padding: '3px 7px',
                      borderRadius: '6px',
                      transform: 'scale(1)',
                    }}
                  >
                    {'TEACHER REVIEW'}
                  </span>
                </span>
                <span style={{ fontFamily: 'var(--brand-mono)' }}>{'72%'}</span>
              </div>
              <div
                style={{
                  height: '10px',
                  borderRadius: '5px',
                  background: 'var(--brand-art-26)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: '72%',
                    height: '100%',
                    borderRadius: '5px',
                    background: 'var(--brand-art-11)',
                    transformOrigin: 'left',
                    transform: 'scaleX(1)',
                  }}
                ></div>
              </div>
            </div>
          </div>
        </div>
      )
    case 'predicted':
      return (
        <div className="brand-art">
          <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
            <div
              style={{
                width: '104px',
                height: '104px',
                borderRadius: '24px',
                overflow: 'hidden',
                boxShadow: '0 16px 30px -16px var(--brand-art-30)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  transform: 'translateY(-208px)',
                }}
              >
                <div
                  style={{
                    height: '104px',
                    background: 'var(--brand-art-7)',
                    color: 'var(--brand-art-6)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontFamily: 'var(--brand-display)',
                    fontWeight: '800',
                    fontSize: '60px',
                  }}
                >
                  {'C'}
                </div>
                <div
                  style={{
                    height: '104px',
                    background: 'var(--brand-art-8)',
                    color: 'var(--brand-art-6)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontFamily: 'var(--brand-display)',
                    fontWeight: '800',
                    fontSize: '60px',
                  }}
                >
                  {'B'}
                </div>
                <div
                  style={{
                    height: '104px',
                    background: 'var(--brand-art-9)',
                    color: 'var(--brand-art-6)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontFamily: 'var(--brand-display)',
                    fontWeight: '800',
                    fontSize: '60px',
                  }}
                >
                  {'A'}
                </div>
              </div>
            </div>
            <div
              style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}
            >
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  letterSpacing: '0.06em',
                  color: 'var(--brand-art-3)',
                }}
              >
                {'PREDICTED \u00b7 PHYSICS'}
              </span>
              <span
                style={{
                  fontFamily: 'var(--brand-display)',
                  fontWeight: '800',
                  fontSize: '30px',
                  letterSpacing: '-0.02em',
                }}
              >
                {'On track for A'}
              </span>
              <span style={{ fontSize: '14px', color: 'var(--brand-art-3)' }}>
                {'A* is 6 marks away'}
              </span>
            </div>
          </div>
        </div>
      )
    case 'clusters':
      return (
        <div className="brand-art">
          <div
            style={{
              width: '100%',
              maxWidth: '380px',
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '14px',
            }}
          >
            <div
              style={{
                background: 'var(--brand-art-37)',
                borderRadius: '16px',
                padding: '14px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
                minHeight: '150px',
              }}
            >
              <span
                style={{
                  fontWeight: '800',
                  fontSize: '15px',
                  color: 'var(--brand-art-38)',
                }}
              >
                {'Units & SI'}
              </span>
              <span
                style={{
                  background: 'var(--brand-art-6)',
                  color: 'var(--brand-art-39)',
                  borderRadius: '8px',
                  padding: '6px 9px',
                  fontSize: '12px',
                  fontFamily: 'var(--brand-mono)',
                  opacity: '1',
                }}
              >
                {'P4 Q3(a) \u22121'}
              </span>
              <span
                style={{
                  background: 'var(--brand-art-6)',
                  color: 'var(--brand-art-39)',
                  borderRadius: '8px',
                  padding: '6px 9px',
                  fontSize: '12px',
                  fontFamily: 'var(--brand-mono)',
                  opacity: '1',
                }}
              >
                {'P4 Q3(c) \u22121'}
              </span>
              <span
                style={{
                  background: 'var(--brand-art-6)',
                  color: 'var(--brand-art-39)',
                  borderRadius: '8px',
                  padding: '6px 9px',
                  fontSize: '12px',
                  fontFamily: 'var(--brand-mono)',
                  opacity: '1',
                }}
              >
                {'P2 Q5 \u22122'}
              </span>
            </div>
            <div
              style={{
                background: 'var(--brand-art-37)',
                borderRadius: '16px',
                padding: '14px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
                minHeight: '150px',
              }}
            >
              <span
                style={{
                  fontWeight: '800',
                  fontSize: '15px',
                  color: 'var(--brand-art-38)',
                }}
              >
                {'Graph reading'}
              </span>
              <span
                style={{
                  background: 'var(--brand-art-6)',
                  color: 'var(--brand-art-39)',
                  borderRadius: '8px',
                  padding: '6px 9px',
                  fontSize: '12px',
                  fontFamily: 'var(--brand-mono)',
                  opacity: '1',
                }}
              >
                {'P3 Q2(b) \u22122'}
              </span>
              <span
                style={{
                  background: 'var(--brand-art-6)',
                  color: 'var(--brand-art-39)',
                  borderRadius: '8px',
                  padding: '6px 9px',
                  fontSize: '12px',
                  fontFamily: 'var(--brand-mono)',
                  opacity: '1',
                }}
              >
                {'P1 Q6 \u22121'}
              </span>
            </div>
          </div>
        </div>
      )
    case 'trends':
      return (
        <div className="brand-art">
          <div
            style={{
              width: '100%',
              maxWidth: '380px',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
            }}
          >
            <div
              style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}
            >
              <span
                style={{
                  fontFamily: 'var(--brand-display)',
                  fontWeight: '800',
                  fontSize: '40px',
                  letterSpacing: '-0.03em',
                  color: 'var(--brand-art-5)',
                }}
              >
                {'+18%'}
              </span>
              <span style={{ fontSize: '14px', color: 'var(--brand-art-3)' }}>
                {'class average this term'}
              </span>
            </div>
            <svg
              viewBox="0 0 380 120"
              style={{ width: '100%', height: 'auto', overflow: 'visible' }}
            >
              <path
                d="M10 100 L80 86 L150 92 L220 60 L290 48 L370 18"
                fill="none"
                stroke="var(--brand-art-5)"
                strokeWidth="4"
                strokeLinecap="round"
                strokeLinejoin="round"
                pathLength="1"
                strokeDasharray="1"
                strokeDashoffset="0"
                style={{}}
              ></path>
              <path
                d="M10 108 L80 104 L150 100 L220 94 L290 84 L370 76"
                fill="none"
                stroke="var(--brand-art-12)"
                strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray="2 7"
              ></path>
              <circle
                cx="370"
                cy="18"
                r="7"
                fill="var(--brand-art-6)"
                stroke="var(--brand-art-5)"
                strokeWidth="4"
                style={{
                  transformBox: 'fill-box',
                  transformOrigin: 'center',
                  transform: 'scale(1)',
                }}
              ></circle>
            </svg>
            <div
              style={{
                display: 'flex',
                gap: '16px',
                fontFamily: 'var(--brand-mono)',
                fontSize: '11px',
                color: 'var(--brand-art-3)',
              }}
            >
              <span
                style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <span
                  style={{
                    width: '14px',
                    height: '3px',
                    background: 'var(--brand-art-5)',
                    borderRadius: '2px',
                  }}
                ></span>
                {'LAYAN'}
              </span>
              <span
                style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <span
                  style={{
                    width: '14px',
                    height: '3px',
                    background: 'var(--brand-art-12)',
                    borderRadius: '2px',
                  }}
                ></span>
                {'CLASS'}
              </span>
            </div>
          </div>
        </div>
      )
    case 'plan':
      return (
        <div className="brand-art">
          <div
            style={{
              width: '100%',
              maxWidth: '360px',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                background: 'var(--brand-art-6)',
                borderRadius: '12px',
                padding: '10px 12px',
              }}
            >
              <svg width="22" height="22" viewBox="0 0 22 22">
                <rect
                  x="1"
                  y="1"
                  width="20"
                  height="20"
                  rx="6"
                  fill="none"
                  stroke="var(--brand-art-33)"
                  strokeWidth="2"
                ></rect>
                <path
                  d="M6 11 L10 15 L16 7"
                  fill="none"
                  stroke="var(--brand-art-5)"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  pathLength="1"
                  strokeDasharray="1"
                  strokeDashoffset="0"
                  style={{}}
                ></path>
              </svg>
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  color: 'var(--brand-art-3)',
                  width: '30px',
                }}
              >
                {'MON'}
              </span>
              <span style={{ fontSize: '14px', fontWeight: '600' }}>
                {'Units drill \u00b7 10 questions'}
              </span>
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                background: 'var(--brand-art-6)',
                borderRadius: '12px',
                padding: '10px 12px',
              }}
            >
              <svg width="22" height="22" viewBox="0 0 22 22">
                <rect
                  x="1"
                  y="1"
                  width="20"
                  height="20"
                  rx="6"
                  fill="none"
                  stroke="var(--brand-art-33)"
                  strokeWidth="2"
                ></rect>
                <path
                  d="M6 11 L10 15 L16 7"
                  fill="none"
                  stroke="var(--brand-art-5)"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  pathLength="1"
                  strokeDasharray="1"
                  strokeDashoffset="0"
                  style={{}}
                ></path>
              </svg>
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  color: 'var(--brand-art-3)',
                  width: '30px',
                }}
              >
                {'TUE'}
              </span>
              <span style={{ fontSize: '14px', fontWeight: '600' }}>
                {'Redo Paper 2 \u00b7 Q5'}
              </span>
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                background: 'var(--brand-art-6)',
                borderRadius: '12px',
                padding: '10px 12px',
              }}
            >
              <svg width="22" height="22" viewBox="0 0 22 22">
                <rect
                  x="1"
                  y="1"
                  width="20"
                  height="20"
                  rx="6"
                  fill="none"
                  stroke="var(--brand-art-33)"
                  strokeWidth="2"
                ></rect>
                <path
                  d="M6 11 L10 15 L16 7"
                  fill="none"
                  stroke="var(--brand-art-5)"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  pathLength="1"
                  strokeDasharray="1"
                  strokeDashoffset="0"
                  style={{}}
                ></path>
              </svg>
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  color: 'var(--brand-art-3)',
                  width: '30px',
                }}
              >
                {'WED'}
              </span>
              <span style={{ fontSize: '14px', fontWeight: '600' }}>
                {'Graph reading \u00b7 flash set'}
              </span>
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                background: 'var(--brand-art-2)',
                borderRadius: '12px',
                padding: '10px 12px',
              }}
            >
              <svg width="22" height="22" viewBox="0 0 22 22">
                <rect
                  x="1"
                  y="1"
                  width="20"
                  height="20"
                  rx="6"
                  fill="none"
                  stroke="var(--brand-art-5)"
                  strokeWidth="2"
                ></rect>
              </svg>
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  color: 'var(--brand-art-5)',
                  width: '30px',
                }}
              >
                {'THU'}
              </span>
              <span
                style={{
                  fontSize: '14px',
                  fontWeight: '700',
                  color: 'var(--brand-art-5)',
                }}
              >
                {'Timed Paper 4 \u00b7 75 min'}
              </span>
            </div>
          </div>
        </div>
      )
    case 'xp':
      return (
        <div className="brand-art">
          <div
            style={{
              width: '100%',
              maxWidth: '380px',
              display: 'flex',
              alignItems: 'center',
              gap: '18px',
            }}
          >
            <svg
              width="92"
              height="101"
              viewBox="0 0 200 220"
              style={{ flexShrink: '0', overflow: 'visible' }}
            >
              <rect
                x="54"
                y="168"
                width="92"
                height="48"
                rx="4"
                fill="var(--brand-art-6)"
                stroke="var(--brand-art-14)"
                strokeWidth="2"
                transform="rotate(-3 100 192)"
              ></rect>
              <g transform="rotate(-10 75 100)">
                <path
                  d="M66 102 L62 40 Q62 16 75 16 Q88 16 88 40 L84 102"
                  fill="none"
                  stroke="var(--brand-art-16)"
                  strokeWidth="7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                ></path>
              </g>
              <g transform="rotate(14 125 100)">
                <path
                  d="M116 102 L112 40 Q112 16 125 16 Q138 16 138 40 L134 102"
                  fill="none"
                  stroke="var(--brand-art-16)"
                  strokeWidth="7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                ></path>
              </g>
              <path
                d="M40 104 H160 L152 186 Q151 196 141 196 H59 Q49 196 48 186 Z"
                fill="var(--brand-art-5)"
              ></path>
              <rect
                x="34"
                y="94"
                width="132"
                height="18"
                rx="8"
                fill="var(--brand-art-17)"
              ></rect>
              <ellipse
                cx="62"
                cy="160"
                rx="9"
                ry="5.5"
                fill="var(--brand-art-18)"
                opacity="0.55"
              ></ellipse>
              <ellipse
                cx="138"
                cy="160"
                rx="9"
                ry="5.5"
                fill="var(--brand-art-18)"
                opacity="0.55"
              ></ellipse>
              <ellipse
                cx="78"
                cy="140"
                rx="11"
                ry="12"
                fill="var(--brand-art-6)"
              ></ellipse>
              <circle
                cx="79"
                cy="141"
                r="6.5"
                fill="var(--brand-art-19)"
              ></circle>
              <path
                d="M112 143 Q122 130 132 143"
                fill="none"
                stroke="var(--brand-art-6)"
                strokeWidth="5"
                strokeLinecap="round"
              ></path>
              <path
                d="M90 166 Q103 171 112 160"
                fill="none"
                stroke="var(--brand-art-6)"
                strokeWidth="4.5"
                strokeLinecap="round"
              ></path>
              <g transform="translate(150 54)">
                <g
                  style={{
                    transformBox: 'fill-box',
                    transformOrigin: '50% 100%',
                  }}
                >
                  <path
                    d="M0 -26 C14 -10 18 2 12 14 C8 22 -8 22 -12 14 C-16 4 -10 -4 -6 -10 C-4 -2 0 0 2 -4 C4 -12 0 -18 0 -26Z"
                    fill="var(--brand-art-34)"
                  ></path>
                  <path
                    d="M0 -6 C6 2 8 8 4 13 C1 16 -4 16 -6 12 C-8 6 -3 2 0 -6Z"
                    fill="var(--brand-art-11)"
                  ></path>
                </g>
              </g>
            </svg>
            <div
              style={{
                flex: '1',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'baseline',
                }}
              >
                <span style={{ fontWeight: '800', fontSize: '16px' }}>
                  {'Level 7'}
                </span>
                <span
                  style={{
                    fontFamily: 'var(--brand-mono)',
                    fontSize: '13px',
                    color: 'var(--brand-art-35)',
                  }}
                >
                  {'+120 XP'}
                </span>
              </div>
              <div
                style={{
                  height: '12px',
                  borderRadius: '6px',
                  background: 'var(--brand-art-26)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: '78%',
                    height: '100%',
                    borderRadius: '6px',
                    background: 'var(--brand-art-11)',
                    transformOrigin: 'left',
                    transform: 'scaleX(1)',
                  }}
                ></div>
              </div>
              <span style={{ fontSize: '14px', color: 'var(--brand-art-3)' }}>
                {'12-day streak \u00b7 Mark Scheme Whisperer'}
              </span>
            </div>
          </div>
        </div>
      )
    case 'content':
      return (
        <div className="brand-art">
          <div
            style={{
              width: '100%',
              maxWidth: '440px',
              background: 'var(--brand-art-6)',
              borderRadius: '16px',
              padding: '18px 20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
              boxShadow: '0 1px 0 var(--brand-art-20)',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '10px',
              }}
            >
              <span style={{ fontWeight: '800', fontSize: '15px' }}>
                {'Worksheet \u00b7 Units & SI'}
              </span>
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '10px',
                  letterSpacing: '0.06em',
                  background: 'var(--brand-art-2)',
                  color: 'var(--brand-art-5)',
                  padding: '4px 8px',
                  borderRadius: '6px',
                  transform: 'scale(1)',
                }}
              >
                {'10 Qs + MARK SCHEME'}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  color: 'var(--brand-art-3)',
                }}
              >
                {'1'}
              </span>
              <div
                style={{
                  height: '8px',
                  width: '86%',
                  borderRadius: '4px',
                  background: 'var(--brand-art-36)',
                  transformOrigin: 'left',
                  transform: 'scaleX(1)',
                }}
              ></div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  color: 'var(--brand-art-3)',
                }}
              >
                {'2'}
              </span>
              <div
                style={{
                  height: '8px',
                  width: '64%',
                  borderRadius: '4px',
                  background: 'var(--brand-art-36)',
                  transformOrigin: 'left',
                  transform: 'scaleX(1)',
                }}
              ></div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  color: 'var(--brand-art-3)',
                }}
              >
                {'3'}
              </span>
              <div
                style={{
                  height: '8px',
                  width: '78%',
                  borderRadius: '4px',
                  background: 'var(--brand-art-36)',
                  transformOrigin: 'left',
                  transform: 'scaleX(1)',
                }}
              ></div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span
                style={{
                  fontFamily: 'var(--brand-mono)',
                  fontSize: '11px',
                  color: 'var(--brand-art-3)',
                }}
              >
                {'4'}
              </span>
              <div
                style={{
                  height: '8px',
                  width: '52%',
                  borderRadius: '4px',
                  background: 'var(--brand-art-36)',
                  transformOrigin: 'left',
                  transform: 'scaleX(1)',
                }}
              ></div>
            </div>
          </div>
        </div>
      )
  }
}
