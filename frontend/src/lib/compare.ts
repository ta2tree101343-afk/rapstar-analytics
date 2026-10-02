import type { CompareSeries, HistoryPoint } from "../api/types";

export type CompareMetric = "viewCount" | "likeCount" | "commentsCount";

export const METRIC_LABEL: Record<CompareMetric, string> = {
  viewCount: "再生数",
  likeCount: "いいね数",
  commentsCount: "コメント数",
};

/**
 * Baseline used for delta-since-first mode. Represents the earliest actual
 * measurement of `metric` inside the current visible range.
 */
export interface DeltaBaseline {
  postId: string;
  rapperName: string | null;
  baselineFetchedAt: string;
  baselineValue: number;
  pointCount: number;
}

export interface DeltaTransformResult {
  series: CompareSeries;
  baseline: DeltaBaseline | null;
  /** True if the transformed series has <2 measurement points (no trend visible). */
  insufficient: boolean;
}

export interface HistoryDeltaResult {
  points: HistoryPoint[];
  baselineFetchedAt: string | null;
  baselineValue: number | null;
  /** True if the transformed points have <2 measurement points (no trend visible). */
  insufficient: boolean;
}

/**
 * Core rebasing logic: rewrite a `HistoryPoint[]` as (value - baseline) for the
 * requested metric. Shared by the compare view (per-series) and the individual
 * post detail view (per-metric).
 *
 * Rules:
 *   - Baseline = the first chronologically observed non-null value of `metric`.
 *   - Points BEFORE the baseline are dropped (no interpolation).
 *   - Points AT baseline become 0.
 *   - Points AFTER baseline become (value - baseline). Null stays null —
 *     never zero-filled. Negative deltas are preserved.
 *   - Other metrics on the same point are passed through unchanged.
 *   - If no non-null observation exists, points is empty and baseline is null.
 *   - If exactly one non-null observation exists, points has a single 0 entry
 *     and `insufficient` is true.
 */
export function transformHistoryToDelta(
  points: HistoryPoint[],
  metric: CompareMetric,
): HistoryDeltaResult {
  const sorted = points
    .slice()
    .sort((a, b) => new Date(a.fetchedAt).getTime() - new Date(b.fetchedAt).getTime());

  let baselineIdx = -1;
  for (let i = 0; i < sorted.length; i++) {
    const v = sorted[i][metric];
    if (v !== null && v !== undefined) {
      baselineIdx = i;
      break;
    }
  }
  if (baselineIdx === -1) {
    return {
      points: [],
      baselineFetchedAt: null,
      baselineValue: null,
      insufficient: true,
    };
  }

  const baselineValue = sorted[baselineIdx][metric] as number;
  const baselineFetchedAt = sorted[baselineIdx].fetchedAt;

  const transformed: HistoryPoint[] = sorted.slice(baselineIdx).map((p) => {
    const rebase = (v: number | null | undefined): number | null =>
      v === null || v === undefined ? null : v - baselineValue;
    return {
      fetchedAt: p.fetchedAt,
      viewCount: metric === "viewCount" ? rebase(p.viewCount) : p.viewCount,
      likeCount: metric === "likeCount" ? rebase(p.likeCount) : p.likeCount,
      commentsCount: metric === "commentsCount" ? rebase(p.commentsCount) : p.commentsCount,
    };
  });

  return {
    points: transformed,
    baselineFetchedAt,
    baselineValue,
    insufficient: transformed.length < 2,
  };
}

export function transformSeriesToDelta(
  series: CompareSeries,
  metric: CompareMetric,
): DeltaTransformResult {
  const r = transformHistoryToDelta(series.points, metric);
  if (r.baselineFetchedAt === null) {
    return {
      series: { ...series, points: [] },
      baseline: null,
      insufficient: true,
    };
  }
  return {
    series: { ...series, points: r.points },
    baseline: {
      postId: series.postId,
      rapperName: series.rapperName,
      baselineFetchedAt: r.baselineFetchedAt,
      baselineValue: r.baselineValue as number,
      pointCount: r.points.length,
    },
    insufficient: r.insufficient,
  };
}

export function colorForPostId(postId: string, salt = 0): string {
  let h = salt;
  for (let i = 0; i < postId.length; i++) h = (h * 31 + postId.charCodeAt(i)) >>> 0;
  const hue = h % 360;
  const sat = 70 + ((h >> 8) % 20); // 70–89
  const light = 55 + ((h >> 16) % 10); // 55–64
  return `hsl(${hue}, ${sat}%, ${light}%)`;
}

/**
 * Prepare data for Recharts. Each series is emitted with its own actual
 * fetched_at values — we do NOT bucket by day nor pretend measurements from
 * different times share the same X coordinate.
 */
export interface RechartsSeriesPoint {
  t: number;
  v: number | null;
  fetchedAt: string;
}

export interface RechartsSeries {
  postId: string;
  rapperName: string | null;
  color: string;
  data: RechartsSeriesPoint[];
}

export function buildRechartsSeries(
  seriesList: CompareSeries[],
  metric: CompareMetric,
): RechartsSeries[] {
  return seriesList.map((s) => ({
    postId: s.postId,
    rapperName: s.rapperName,
    color: colorForPostId(s.postId),
    data: s.points
      .map((p) => ({
        t: new Date(p.fetchedAt).getTime(),
        v: p[metric],
        fetchedAt: p.fetchedAt,
      }))
      .sort((a, b) => a.t - b.t),
  }));
}

export interface AsOfSnapshotEntry {
  postId: string;
  rapperName: string | null;
  color: string;
  /**
   * Latest non-null value of the series' metric whose fetched_at is ≤
   * `selectedT`. Null when the series has no measurement in the allowed
   * window — callers must render "データなし" rather than treating null as 0.
   */
  value: number | null;
  /** Actual fetched_at of the measurement backing `value`. */
  actualFetchedAt: string | null;
  /** selectedT − actualFetched_at in ms. Null when there is no as-of data. */
  ageMs: number | null;
}

/** Collection cycle = one Collector Lambda run that actually wrote snapshots.
 * Boundaries come from the fetch-runs table (`started_at`, `finished_at`),
 * so we associate each measurement with its true producing run rather than
 * guessing from `fetched_at` clustering. `LockTable` guarantees runs do not
 * overlap in time, so `[startedAt, finishedAt]` intervals are disjoint. */
export interface CollectionCycle {
  runId: string;
  startedAt: number;
  finishedAt: number;
  status: string | null;
}

export interface CycleSnapshotEntry {
  postId: string;
  rapperName: string | null;
  color: string;
  /** The point in this cycle for this series. `null` when this series did not
   * produce a measurement in this cycle (partial run, per-post failure, or
   * the post did not exist yet). */
  value: number | null;
  /** Actual fetched_at for the returned point, or `null` when no in-cycle
   * measurement exists. */
  actualFetchedAt: string | null;
  /** True when the series has a measurement in this cycle. False when it does
   * not — value is null and the UI should render "この収集回のデータなし". */
  inCycle: boolean;
}

/** Rounding tolerance (ms) applied to a cycle's [started_at, finished_at]
 * envelope when matching snapshots. Absorbs sub-second clock skew between
 * fetch-run bookkeeping and the individual snapshot puts inside the run. */
const CYCLE_MATCH_TOLERANCE_MS = 5_000;

export function buildCycles(runs: {
  runId: string;
  startedAt: string;
  finishedAt: string;
  status: string | null;
}[]): CollectionCycle[] {
  const cycles = runs
    .map((r) => ({
      runId: r.runId,
      startedAt: new Date(r.startedAt).getTime(),
      finishedAt: new Date(r.finishedAt).getTime(),
      status: r.status,
    }))
    .filter((c) => Number.isFinite(c.startedAt) && Number.isFinite(c.finishedAt))
    .sort((a, b) => a.startedAt - b.startedAt);
  return cycles;
}

/**
 * Pick the cycle source: authoritative API `runs` if the backend returned
 * any, otherwise fall back to clustering the visible series' measurement
 * timestamps. Centralises the "which source do we trust" decision so the
 * ComparePage doesn't have to repeat it inline, and so the preference order
 * is unit-testable without rendering the component.
 *
 * The authoritative path returns ONLY `buildCycles(apiRuns)` entries — this
 * function never mixes synthetic cycles in. If the authoritative path is
 * taken, callers can safely assume no `runId` starts with `"synthetic-"`.
 */
export function resolveCycles(
  apiRuns:
    | {
        runId: string;
        startedAt: string;
        finishedAt: string;
        status: string | null;
      }[]
    | undefined
    | null,
  series: RechartsSeries[],
): CollectionCycle[] {
  if (apiRuns && apiRuns.length > 0) return buildCycles(apiRuns);
  return synthesizeCyclesFromSeries(series);
}

/**
 * Fallback cycle synthesis used when the API does not (yet) return `runs`.
 * We cluster the visible series' unique measurement timestamps by proximity
 * (`gapMs` default 5 minutes) — each cluster becomes one implicit cycle.
 *
 * This is a DEGRADATION path, not the primary source. When the backend
 * returns real fetch-run intervals, callers should prefer those. Two
 * consequences to be aware of:
 *   - Two genuinely-distinct runs firing within `gapMs` (e.g. a manual
 *     invocation immediately after the scheduler) will be merged into one
 *     implicit cycle here.
 *   - A partial run where every series' measurement fell inside `gapMs` of
 *     the previous run's measurements will also be merged.
 * The real `runs` payload (see `buildCycles`) resolves both cases.
 */
export function synthesizeCyclesFromSeries(
  series: RechartsSeries[],
  gapMs: number = 5 * 60_000,
): CollectionCycle[] {
  const times = new Set<number>();
  for (const s of series) {
    for (const p of s.data) times.add(p.t);
  }
  const sorted = Array.from(times).sort((a, b) => a - b);
  const cycles: CollectionCycle[] = [];
  let clusterStart: number | null = null;
  let clusterEnd = 0;
  const flush = () => {
    if (clusterStart === null) return;
    cycles.push({
      runId: `synthetic-${cycles.length + 1}`,
      startedAt: clusterStart,
      finishedAt: clusterEnd,
      status: "synthetic",
    });
  };
  for (const t of sorted) {
    if (clusterStart === null || t - clusterEnd > gapMs) {
      flush();
      clusterStart = t;
    }
    clusterEnd = t;
  }
  flush();
  return cycles;
}

/** Find the cycle that contains time `t`, or the nearest one if `t` lies in
 * the gap between cycles. Returns null when there are no cycles at all.
 *
 * "Contains" uses ±CYCLE_MATCH_TOLERANCE_MS around the cycle envelope so a
 * user click that snaps to a measurement's exact `fetched_at` at the very
 * edge still resolves to the containing cycle.
 *
 * Between cycles, we pick the cycle whose envelope midpoint is closest to
 * `t` — with ties broken toward the earlier cycle so a selection at the
 * start of a gap sticks to the run that produced the last observation. */
export function findCycleForTime(
  t: number,
  cycles: CollectionCycle[],
): CollectionCycle | null {
  if (cycles.length === 0) return null;
  for (const c of cycles) {
    if (
      t >= c.startedAt - CYCLE_MATCH_TOLERANCE_MS &&
      t <= c.finishedAt + CYCLE_MATCH_TOLERANCE_MS
    ) {
      return c;
    }
  }
  let best: CollectionCycle = cycles[0];
  let bestDist = Math.abs(t - (best.startedAt + best.finishedAt) / 2);
  for (let i = 1; i < cycles.length; i++) {
    const c = cycles[i];
    const mid = (c.startedAt + c.finishedAt) / 2;
    const d = Math.abs(t - mid);
    if (d < bestDist) {
      best = c;
      bestDist = d;
    }
  }
  return best;
}

/** For each series, return the single measurement produced by `cycle` (i.e.
 * whose `t` falls within the cycle's envelope, with the same tolerance).
 * Does NOT fall back to earlier cycles: if the series was not measured in
 * this cycle, the entry has `inCycle: false` and `value: null`.
 *
 * Sorted so that in-cycle entries come first (by value desc), then out-of-
 * cycle entries. Null values within in-cycle group land at the end of that
 * group. */
export function computeCycleSnapshot(
  cycle: CollectionCycle,
  series: RechartsSeries[],
): CycleSnapshotEntry[] {
  const lo = cycle.startedAt - CYCLE_MATCH_TOLERANCE_MS;
  const hi = cycle.finishedAt + CYCLE_MATCH_TOLERANCE_MS;
  const rows: CycleSnapshotEntry[] = series.map((s) => {
    let match: RechartsSeriesPoint | null = null;
    for (const p of s.data) {
      if (p.t < lo) continue;
      if (p.t > hi) break;
      // Multiple points in one cycle should not happen (distributed lock),
      // but if it does, prefer the last one — it reflects the final write.
      match = p;
    }
    return {
      postId: s.postId,
      rapperName: s.rapperName,
      color: s.color,
      value: match ? match.v : null,
      actualFetchedAt: match ? match.fetchedAt : null,
      inCycle: match !== null,
    };
  });
  rows.sort((a, b) => {
    if (a.inCycle !== b.inCycle) return a.inCycle ? -1 : 1;
    if (a.value === null && b.value === null) return 0;
    if (a.value === null) return 1;
    if (b.value === null) return -1;
    return b.value - a.value;
  });
  return rows;
}

/**
 * For each series, return the most recent non-null measurement whose
 * fetched_at is ≤ `selectedT`. Never interpolates, never uses future
 * measurements, never zero-fills. This is the "as-of" semantics that lets
 * us compare multiple series at a single reference time without pretending
 * they were all measured simultaneously.
 *
 * Ordering: non-null values first, descending — so the tooltip lists the
 * highest values on top for easy comparison. Empty entries follow.
 */
export function computeAsOfSnapshot(
  selectedT: number,
  series: RechartsSeries[],
): AsOfSnapshotEntry[] {
  const rows = series.map((s) => {
    let latest: RechartsSeriesPoint | null = null;
    // s.data is guaranteed sorted ascending by t (buildRechartsSeries).
    for (const p of s.data) {
      if (p.t > selectedT) break;
      if (p.v !== null) latest = p;
    }
    return {
      postId: s.postId,
      rapperName: s.rapperName,
      color: s.color,
      value: latest ? latest.v : null,
      actualFetchedAt: latest ? latest.fetchedAt : null,
      ageMs: latest ? selectedT - latest.t : null,
    };
  });
  rows.sort((a, b) => {
    if (a.value === null && b.value === null) return 0;
    if (a.value === null) return 1;
    if (b.value === null) return -1;
    return b.value - a.value;
  });
  return rows;
}

export interface AsOfMarker {
  postId: string;
  color: string;
  t: number;
  /**
   * Y coordinate in DATA space. When `isExact` is true this is the actual
   * measurement value at t; when false it's the linear interpolation between
   * the two flanking measurements (matching Recharts' `type="linear"` draw).
   */
  y: number;
  /**
   * True when a real measurement exists at exactly `selectedT`; false when
   * the marker is a reference position on the drawn line segment (no
   * measurement was taken at this instant).
   */
  isExact: boolean;
}

/**
 * For each series, compute where to place a selection marker on the drawn
 * polyline at `selectedT`. Distinguishes between "actual measurement exists at
 * this instant" (isExact=true, render as filled circle) and "position along
 * the interpolated segment" (isExact=false, render as hollow circle) so we
 * never invent measurement points that weren't actually taken.
 *
 * A series contributes NO marker when selectedT lies outside its drawn
 * segments (i.e. before its first or after its last non-null measurement) —
 * there is no line to sit on in that region.
 */
export function computeAsOfMarkers(
  selectedT: number,
  series: RechartsSeries[],
): AsOfMarker[] {
  const markers: AsOfMarker[] = [];
  for (const s of series) {
    let before: RechartsSeriesPoint | null = null;
    let after: RechartsSeriesPoint | null = null;
    for (const p of s.data) {
      if (p.v === null) continue;
      if (p.t <= selectedT) before = p;
      else {
        after = p;
        break;
      }
    }
    if (before && before.t === selectedT) {
      markers.push({
        postId: s.postId,
        color: s.color,
        t: selectedT,
        y: before.v as number,
        isExact: true,
      });
      continue;
    }
    if (before && after) {
      const span = after.t - before.t;
      const ratio = span === 0 ? 0 : (selectedT - before.t) / span;
      const y = (before.v as number) + ((after.v as number) - (before.v as number)) * ratio;
      markers.push({
        postId: s.postId,
        color: s.color,
        t: selectedT,
        y,
        isExact: false,
      });
    }
    // else: selectedT is outside this series' drawn range → no marker.
  }
  return markers;
}

export interface CycleMarker {
  postId: string;
  color: string;
  t: number;
  y: number;
}

/**
 * Marker positions to render on the chart when a collection cycle is
 * selected. Mirrors `computeCycleSnapshot` but returns only the {t, y}
 * needed for placement — one entry per series that produced a **non-null**
 * measurement in the given cycle. Series without an in-cycle measurement
 * yield no marker (they will appear as "この収集回のデータなし" in the
 * panel, and no dot on the chart).
 *
 * All returned markers should be rendered with the same styling so a click
 * anywhere in the cycle yields the same visual result for every series.
 */
export function computeCycleMarkers(
  cycle: CollectionCycle,
  series: RechartsSeries[],
): CycleMarker[] {
  const lo = cycle.startedAt - 5_000;
  const hi = cycle.finishedAt + 5_000;
  const out: CycleMarker[] = [];
  for (const s of series) {
    let match: RechartsSeriesPoint | null = null;
    for (const p of s.data) {
      if (p.t < lo) continue;
      if (p.t > hi) break;
      match = p;
    }
    if (match !== null && match.v !== null) {
      out.push({
        postId: s.postId,
        color: s.color,
        t: match.t,
        y: match.v,
      });
    }
  }
  return out;
}

export function uniqueMeasurementTimes(series: RechartsSeries[]): number[] {
  const set = new Set<number>();
  for (const s of series) {
    for (const p of s.data) {
      if (p.v !== null) set.add(p.t);
    }
  }
  return Array.from(set).sort((a, b) => a - b);
}

export function topNByLatest(
  seriesList: CompareSeries[],
  metric: CompareMetric,
  n: number,
): string[] {
  const ranked = seriesList
    .map((s) => {
      let latest: number | null = null;
      for (let i = s.points.length - 1; i >= 0; i--) {
        const v = s.points[i][metric];
        if (v !== null && v !== undefined) {
          latest = v;
          break;
        }
      }
      return { postId: s.postId, latest };
    })
    .filter((x) => x.latest !== null)
    .sort((a, b) => (b.latest as number) - (a.latest as number));
  return ranked.slice(0, n).map((x) => x.postId);
}
