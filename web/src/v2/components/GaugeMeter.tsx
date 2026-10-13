import DockTooltip from "./DockTooltip";

interface Props {
  label: string;
  percent: number;
  tooltip: string;
  index?: number;
}

const CX = 40;
const CY = 38;
const R = 26;
const STROKE = 4.5;
const PAD = STROKE / 2 + 3;
const START = 135;
const SWEEP = 270;
const TICKS = [0, 25, 50, 75, 100];
const CIRCUMFERENCE = 2 * Math.PI * R;
const TRACK_LENGTH = CIRCUMFERENCE * (SWEEP / 360);
const ROTATE = START - 90;
const VIEW_W = 80;
const VIEW_H = 72;

function polarToCartesian(angleDeg: number, radius = R) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: CX + radius * Math.cos(rad), y: CY + radius * Math.sin(rad) };
}

function gaugeColor(percent: number): string {
  if (percent >= 85) return "var(--v2-danger)";
  if (percent >= 60) return "var(--v2-accent)";
  return "var(--v2-teal)";
}

export default function GaugeMeter({ label, percent, tooltip, index = 0 }: Props) {
  const clamped = Math.min(100, Math.max(0, percent));
  const fillLength = (clamped / 100) * TRACK_LENGTH;
  const endAngle = START + (SWEEP * clamped) / 100;
  const needle = clamped > 0 ? polarToCartesian(endAngle, R - 4) : null;
  const color = gaugeColor(clamped);
  const id = `gauge-${label.toLowerCase()}`;

  return (
    <DockTooltip
      text={tooltip}
      className="v2-gauge"
      role="meter"
      aria-label={tooltip}
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <svg viewBox={`${-PAD} ${-PAD} ${VIEW_W + PAD * 2} ${VIEW_H + PAD * 2}`} className="v2-gauge-svg" aria-hidden>
        <defs>
          <filter id={`${id}-glow`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {TICKS.map((tick) => {
          const angle = START + (SWEEP * tick) / 100;
          const outer = polarToCartesian(angle, R + 2);
          const inner = polarToCartesian(angle, R - (tick % 50 === 0 ? 5 : 3));
          return (
            <line
              key={tick}
              x1={inner.x}
              y1={inner.y}
              x2={outer.x}
              y2={outer.y}
              className="v2-gauge-tick"
              opacity={tick % 50 === 0 ? 0.55 : 0.28}
            />
          );
        })}
        <g transform={`rotate(${ROTATE} ${CX} ${CY})`}>
          <circle
            cx={CX}
            cy={CY}
            r={R}
            className="v2-gauge-track"
            fill="none"
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={`${TRACK_LENGTH} ${CIRCUMFERENCE}`}
          />
          {clamped > 0 && (
            <circle
              cx={CX}
              cy={CY}
              r={R}
              className="v2-gauge-fill"
              fill="none"
              strokeWidth={STROKE}
              strokeLinecap="round"
              strokeDasharray={`${fillLength} ${CIRCUMFERENCE}`}
              style={{ stroke: color, filter: `url(#${id}-glow)` }}
            />
          )}
        </g>
        {needle && <circle cx={needle.x} cy={needle.y} r={2.5} className="v2-gauge-needle" style={{ fill: color }} />}
        <text
          x={CX}
          y={CY + 4}
          className={`v2-gauge-label${label.length > 3 ? " v2-gauge-label--wide" : ""}`}
          textAnchor="middle"
        >
          {label}
        </text>
      </svg>
    </DockTooltip>
  );
}
