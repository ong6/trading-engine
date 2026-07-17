// Plain inline-SVG polyline equity sparkline — no charting library. Colours by
// net direction (last vs first). Renders nothing meaningful when < 2 points.
export default function Sparkline({ values, width = 220, height = 44 }) {
  const nums = (values || []).filter((v) => typeof v === "number" && Number.isFinite(v));
  if (nums.length < 2) {
    return <span className="faint">not enough points</span>;
  }
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const pad = 3;
  const w = width - pad * 2;
  const h = height - pad * 2;
  const pts = nums.map((v, i) => {
    const x = pad + (i / (nums.length - 1)) * w;
    const y = pad + (1 - (v - min) / span) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const up = nums[nums.length - 1] >= nums[0];
  const stroke = up ? "#3fb950" : "#f85149";
  return (
    <svg
      className="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="equity sparkline"
    >
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
