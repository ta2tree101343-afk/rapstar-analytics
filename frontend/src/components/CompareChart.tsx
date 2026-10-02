import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  computeCycleMarkers,
  type CollectionCycle,
  type RechartsSeries,
} from "../lib/compare";
import { formatNumber } from "../lib/formatters";

interface Props {
  series: RechartsSeries[];
  yLabel: string;
  highlightedIds: Set<string>;
  /**
   * Currently selected time on the X axis (epoch ms). Either the mouse-hover
   * time or the pinned tap time — resolved by the parent. Renders a vertical
   * guideline. `null` = no selection.
   */
  selectedT: number | null;
  /**
   * The collection cycle the selection resolves to. Drives per-series
   * marker placement — each visible series with a measurement in this cycle
   * gets one uniformly-styled marker (colored ring + dark inner + colored
   * halo). Series without an in-cycle measurement get NO marker (matching
   * the panel's "この収集回のデータなし" state). `null` = no markers.
   */
  selectedCycle: CollectionCycle | null;
  /** Fired on mouse-move over the chart. Parent decides whether to honor
   *  it (typically only when no time is pinned). */
  onHoverTime: (t: number | null) => void;
  /** Fired on click / tap. Parent pins this time until explicit clear. */
  onSelectTime: (t: number) => void;
  height?: number;
}

/**
 * Multi-series time chart. Each `<Line>` receives its own `data` prop so
 * measurements from different posts stay at THEIR actual fetched_at. No
 * bucketing by day, no interpolation, no zero-fill for missing values.
 *
 * Selection model: whole-chart X-axis selection rather than per-dot clicks.
 * The chart calls back with the active X (activeLabel from Recharts) on
 * hover and click, and renders a `<ReferenceLine>` at `selectedT`. The
 * per-series as-of values are computed and rendered OUTSIDE this component
 * (see `computeAsOfSnapshot` + the parent's snapshot panel) so we don't have
 * to fight Recharts' default per-line Tooltip semantics.
 *
 * Highlight is opt-in: when `highlightedIds` is non-empty, matching lines
 * are drawn thicker and others are dimmed. `highlightedIds` is orthogonal to
 * inclusion (checkbox in the selection panel) and to visibility (eye icon
 * in the legend).
 */
export function CompareChart({
  series,
  yLabel,
  highlightedIds,
  selectedT,
  selectedCycle,
  onHoverTime,
  onSelectTime,
  height = 380,
}: Props) {
  if (series.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-fg-muted">
        比較対象を選択してください
      </div>
    );
  }
  const hasAnyPoint = series.some((s) => s.data.length > 0);
  if (!hasAnyPoint) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-fg-muted">
        期間内の取得データがありません
      </div>
    );
  }

  let tMin = Number.POSITIVE_INFINITY;
  let tMax = Number.NEGATIVE_INFINITY;
  for (const s of series) {
    for (const p of s.data) {
      if (p.t < tMin) tMin = p.t;
      if (p.t > tMax) tMax = p.t;
    }
  }

  const hasHighlight = highlightedIds.size > 0;

  const ordered = [...series].sort((a, b) => {
    const ah = highlightedIds.has(a.postId) ? 1 : 0;
    const bh = highlightedIds.has(b.postId) ? 1 : 0;
    return ah - bh;
  });

  // Recharts' onMouseMove / onClick pass state.activeLabel which, for a
  // `type="number"` XAxis, is the numeric X value snapped to the nearest
  // measurement across all lines. That's what we forward. `chartX` fallback
  // handles the (rare) case where activeLabel is undefined.
  const readActiveT = (state: any): number | null => {
    if (state == null) return null;
    const label = state.activeLabel;
    if (typeof label === "number" && !Number.isNaN(label)) return label;
    if (typeof label === "string" && label !== "") {
      const n = Number(label);
      if (!Number.isNaN(n)) return n;
    }
    return null;
  };

  const handleMouseMove = (state: any) => {
    const t = readActiveT(state);
    onHoverTime(t);
  };
  const handleClick = (state: any) => {
    const t = readActiveT(state);
    if (t !== null) onSelectTime(t);
  };
  const handleMouseLeave = () => {
    onHoverTime(null);
  };

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-xs font-medium uppercase tracking-wider text-fg-secondary">
          {yLabel}
        </div>
        <div className="text-[11px] text-fg-muted">
          {series.length} 系列を表示中
          {hasHighlight && (
            <span className="ml-2 text-accent-yellow">・強調 {highlightedIds.size} 件</span>
          )}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart
          margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          onClick={handleClick}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#2A2A34" />
          <XAxis
            type="number"
            dataKey="t"
            scale="time"
            domain={[tMin, tMax]}
            allowDuplicatedCategory={false}
            tickFormatter={(t: number) =>
              new Intl.DateTimeFormat("ja-JP", {
                month: "2-digit",
                day: "2-digit",
                timeZone: "Asia/Tokyo",
              }).format(new Date(t))
            }
            stroke="#666673"
            tick={{ fill: "#9A9AA5", fontSize: 11 }}
          />
          <YAxis
            stroke="#666673"
            tick={{ fill: "#9A9AA5", fontSize: 11 }}
            tickFormatter={(v: number) => formatNumber(v)}
            width={64}
          />
          {/* Keep Recharts' active-state tracking (needed for activeLabel /
              activeDot) but suppress its default tooltip UI — the parent
              renders the as-of snapshot panel instead. */}
          <Tooltip content={() => null} cursor={false} />
          {ordered.map((s) => {
            const isHi = highlightedIds.has(s.postId);
            const dim = hasHighlight && !isHi;
            const opacity = dim ? 0.22 : 1;
            const width = isHi ? 3 : dim ? 1 : 1.6;
            return (
              <Line
                key={s.postId}
                data={s.data}
                type="linear"
                dataKey="v"
                name={s.rapperName ?? s.postId}
                stroke={s.color}
                strokeWidth={width}
                strokeOpacity={opacity}
                dot={{
                  r: isHi ? 3 : 2,
                  stroke: s.color,
                  fill: "#0B0B0F",
                  strokeOpacity: opacity,
                }}
                // Recharts' per-line activeDot follows the cursor and would
                // otherwise render a filled dot on the series nearest to the
                // pointer — which visually overlaps our cycle markers and
                // creates the "yellow-filled center" artifact when moving
                // right of the guideline. Our own ReferenceDot markers below
                // are the single source of truth for selection feedback.
                activeDot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            );
          })}
          {selectedT !== null && (
            <ReferenceLine
              x={selectedT}
              stroke="#B8B8C4"
              strokeWidth={1}
              ifOverflow="hidden"
            />
          )}
          {selectedCycle !== null &&
            (() => {
              const markers = computeCycleMarkers(selectedCycle, ordered);
              // Marker size is intentionally NOT scaled down for large series
              // counts. Earlier we shrank halo r 10→6 and core r 5→3 when
              // series > 80, but at 133 series the tiny halo (r=6) became
              // invisible against the dense line stroke overlay — the
              // selection cue was noticeably weaker in "全員" mode than in
              // "上位10人". Keeping halo r=10 / core r=5 uniformly preserves
              // recognition parity across all preset modes; readability at
              // 133 series is aided by the halo's translucency (blur/shadow
              // are NOT used, per the design constraints).
              const CORE_R = 5;
              const HALO_R = 10;
              const HALO_OPACITY = 0.22;
              return markers.map((m) => {
                const isHi = highlightedIds.has(m.postId);
                const r = isHi ? CORE_R + 1 : CORE_R;
                const hR = isHi ? HALO_R + 2 : HALO_R;
                return (
                  <ReferenceDot
                    key={`cycle-marker-${m.postId}`}
                    x={m.t}
                    y={m.y}
                    r={r}
                    ifOverflow="hidden"
                    isFront
                    shape={(props: any) => {
                      const { cx, cy } = props;
                      if (typeof cx !== "number" || typeof cy !== "number") return <g />;
                      return (
                        <g pointerEvents="none">
                          <circle
                            cx={cx}
                            cy={cy}
                            r={hR}
                            fill={m.color}
                            fillOpacity={HALO_OPACITY}
                          />
                          <circle
                            cx={cx}
                            cy={cy}
                            r={r}
                            fill="#0B0B0F"
                            stroke={m.color}
                            strokeWidth={2}
                          />
                        </g>
                      );
                    }}
                  />
                );
              });
            })()}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
