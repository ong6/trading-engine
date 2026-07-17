// Inline-SVG candlestick chart — no charting library. Shows the most recent
// `maxBars` daily bars. Up days green, down days red. Pure/deterministic so it
// renders identically server- and client-side.
import { fmtPrice, fmtDate } from "../lib/format";

export default function PriceChart({ bars, maxBars = 90 }) {
  const all = (bars || []).filter(
    (b) =>
      b &&
      typeof b.high === "number" &&
      typeof b.low === "number" &&
      typeof b.open === "number" &&
      typeof b.close === "number"
  );
  const data = all.slice(-maxBars);
  if (data.length < 2) {
    return <div className="empty">Not enough price bars to chart.</div>;
  }

  const width = 900;
  const height = 320;
  const padL = 52;
  const padR = 10;
  const padT = 10;
  const padB = 22;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const highs = data.map((b) => b.high);
  const lows = data.map((b) => b.low);
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const span = max - min || 1;

  const y = (v) => padT + (1 - (v - min) / span) * plotH;
  const slot = plotW / data.length;
  const bw = Math.max(1, Math.min(10, slot * 0.6));

  // Horizontal gridlines / axis labels at 4 levels.
  const levels = [0, 0.25, 0.5, 0.75, 1].map((f) => min + f * span);

  return (
    <div className="table-wrap" style={{ padding: 8 }}>
      <svg
        className="chart"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="price candlestick chart"
      >
        {levels.map((lv, i) => (
          <g key={i}>
            <line
              x1={padL}
              x2={width - padR}
              y1={y(lv)}
              y2={y(lv)}
              stroke="#2a323d"
              strokeWidth="1"
            />
            <text
              x={padL - 6}
              y={y(lv) + 3}
              textAnchor="end"
              fontSize="10"
              fill="#6b7683"
              fontFamily="monospace"
            >
              {fmtPrice(lv)}
            </text>
          </g>
        ))}
        {data.map((b, i) => {
          const cx = padL + slot * i + slot / 2;
          const up = b.close >= b.open;
          const color = up ? "#3fb950" : "#f85149";
          const yo = y(b.open);
          const yc = y(b.close);
          const top = Math.min(yo, yc);
          const bh = Math.max(1, Math.abs(yc - yo));
          return (
            <g key={b.date || i}>
              <line
                x1={cx}
                x2={cx}
                y1={y(b.high)}
                y2={y(b.low)}
                stroke={color}
                strokeWidth="1"
              />
              <rect
                x={cx - bw / 2}
                y={top}
                width={bw}
                height={bh}
                fill={color}
              />
            </g>
          );
        })}
        {/* first/last date labels */}
        <text
          x={padL}
          y={height - 6}
          fontSize="10"
          fill="#6b7683"
          fontFamily="monospace"
        >
          {fmtDate(data[0].date)}
        </text>
        <text
          x={width - padR}
          y={height - 6}
          textAnchor="end"
          fontSize="10"
          fill="#6b7683"
          fontFamily="monospace"
        >
          {fmtDate(data[data.length - 1].date)}
        </text>
      </svg>
    </div>
  );
}
