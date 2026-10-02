import type { HistoryPoint } from "../api/types";

export const DELTA_TARGET_HOURS = 24;
export const DELTA_TOLERANCE_HOURS = 6;

export type Metric = "viewCount" | "likeCount" | "commentsCount";

export interface DeltaResult {
  delta: number;
  latestValue: number;
  latestFetchedAt: string;
  referenceValue: number;
  referenceFetchedAt: string;
  actualHoursBetween: number;
}

export type DeltaFailure =
  | { kind: "too_new"; postAgeHours: number }
  | { kind: "no_metric" }
  | { kind: "insufficient_data" };

export type DeltaOutcome = { ok: true; result: DeltaResult } | { ok: false; failure: DeltaFailure };

/**
 * Compute delta between the latest sample and the sample nearest to
 * `latest.fetched_at - DELTA_TARGET_HOURS`, provided the reference is within
 * ±DELTA_TOLERANCE_HOURS of that target.
 *
 * IMPORTANT: never interpolate between missing points. Only compare two
 * actual observations. If either observation lacks the metric, return failure.
 */
export function computeDelta(
  points: HistoryPoint[],
  postedAtIso: string,
  metric: Metric,
): DeltaOutcome {
  if (points.length < 2) return { ok: false, failure: { kind: "insufficient_data" } };

  const sorted = [...points].sort(
    (a, b) => new Date(a.fetchedAt).getTime() - new Date(b.fetchedAt).getTime(),
  );

  // "latest" is the most recent observation in time. If that observation
  // lacks the metric we treat this post as having no current metric — we do
  // NOT fall back to an older sample as if it were current.
  const latest = sorted[sorted.length - 1];
  if (latest[metric] === null || latest[metric] === undefined) {
    return { ok: false, failure: { kind: "no_metric" } };
  }

  const latestMs = new Date(latest.fetchedAt).getTime();
  const postedMs = new Date(postedAtIso).getTime();
  const postAgeHours = (latestMs - postedMs) / 3_600_000;
  if (postAgeHours < DELTA_TARGET_HOURS) {
    return { ok: false, failure: { kind: "too_new", postAgeHours } };
  }

  const targetMs = latestMs - DELTA_TARGET_HOURS * 3_600_000;
  const windowMin = latestMs - (DELTA_TARGET_HOURS + DELTA_TOLERANCE_HOURS) * 3_600_000;
  const windowMax = latestMs - (DELTA_TARGET_HOURS - DELTA_TOLERANCE_HOURS) * 3_600_000;

  let best: HistoryPoint | null = null;
  let bestDiff = Number.POSITIVE_INFINITY;
  for (const p of sorted) {
    if (p === latest) continue;
    const ms = new Date(p.fetchedAt).getTime();
    if (ms < windowMin || ms > windowMax) continue;
    if (p[metric] === null || p[metric] === undefined) continue;
    const diff = Math.abs(ms - targetMs);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = p;
    }
  }
  if (!best) return { ok: false, failure: { kind: "insufficient_data" } };

  const latestVal = latest[metric] as number;
  const refVal = best[metric] as number;
  const actualHours = (latestMs - new Date(best.fetchedAt).getTime()) / 3_600_000;
  return {
    ok: true,
    result: {
      delta: latestVal - refVal,
      latestValue: latestVal,
      latestFetchedAt: latest.fetchedAt,
      referenceValue: refVal,
      referenceFetchedAt: best.fetchedAt,
      actualHoursBetween: actualHours,
    },
  };
}
