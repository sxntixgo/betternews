/**
 * A bar chart, hand-rolled in SVG.
 *
 * The alternative was a charting library: 100 KB+ for six charts on a screen
 * visited monthly. `react` and `react-dom` are this app's only dependencies and
 * that is worth keeping — a chart is a rectangle whose height is a ratio, and
 * the axis labels are the only part that needed thought.
 */
export interface Bar {
  label: string;
  value: number;
  /** Drawn under the bar in a second colour, for a like/dislike split. */
  secondary?: number;
  title?: string;
}

export function BarChart({ bars, height = 120, marker }: {
  bars: Bar[];
  height?: number;
  /** 0–1 along the x axis. Used to show where the score threshold falls. */
  marker?: number;
}) {
  // Scale to the tallest bar, not to a round number: these are counts with no
  // natural ceiling, and a fixed one flattens every real distribution.
  const peak = Math.max(1, ...bars.map((b) => b.value + (b.secondary ?? 0)));
  const width = 100;                       // viewBox units; CSS does the sizing
  const gap = 0.15;
  const slot = width / Math.max(1, bars.length);

  return (
    <svg className="bar-chart" viewBox={`0 0 ${width} ${height}`}
         preserveAspectRatio="none" role="img"
         aria-label={`Bar chart of ${bars.length} values, tallest ${peak}`}>
      {bars.map((b, i) => {
        const total = b.value + (b.secondary ?? 0);
        const h = (total / peak) * height;
        const secondaryH = ((b.secondary ?? 0) / peak) * height;
        return (
          <g key={b.label}>
            <rect
              x={i * slot + (slot * gap) / 2} y={height - h}
              width={slot * (1 - gap)} height={h}
              className="bar-primary"
            >
              <title>{b.title ?? `${b.label}: ${b.value}`}</title>
            </rect>
            {b.secondary != null && b.secondary > 0 && (
              <rect
                x={i * slot + (slot * gap) / 2} y={height - secondaryH}
                width={slot * (1 - gap)} height={secondaryH}
                className="bar-secondary"
              >
                <title>{`${b.label}: ${b.secondary}`}</title>
              </rect>
            )}
          </g>
        );
      })}
      {marker != null && (
        // vectorEffect keeps the line 1px after the non-uniform viewBox scale;
        // without it the stretch makes it a fat smear.
        <line className="bar-marker" x1={marker * width} x2={marker * width}
              y1={0} y2={height} vectorEffect="non-scaling-stroke" />
      )}
    </svg>
  );
}
