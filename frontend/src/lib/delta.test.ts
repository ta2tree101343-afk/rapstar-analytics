import { describe, it, expect } from "vitest";
import { computeDelta } from "./delta";
import type { HistoryPoint } from "../api/types";

function pt(hoursAgoFromNow: number, values: Partial<Omit<HistoryPoint, "fetchedAt">>): HistoryPoint {
  const iso = new Date(Date.now() - hoursAgoFromNow * 3_600_000).toISOString();
  return {
    fetchedAt: iso,
    viewCount: values.viewCount ?? null,
    likeCount: values.likeCount ?? null,
    commentsCount: values.commentsCount ?? null,
  };
}

const postedLongAgo = new Date(Date.now() - 30 * 24 * 3_600_000).toISOString();

describe("computeDelta", () => {
  it("returns delta when a reference sits within ±6h of 24h ago", () => {
    const points = [pt(24, { viewCount: 1000 }), pt(0, { viewCount: 1500 })];
    const out = computeDelta(points, postedLongAgo, "viewCount");
    expect(out.ok).toBe(true);
    if (out.ok) {
      expect(out.result.delta).toBe(500);
      expect(out.result.actualHoursBetween).toBeCloseTo(24, 0);
    }
  });

  it("accepts a reference within tolerance (e.g. 20h ago)", () => {
    const points = [pt(20, { viewCount: 1000 }), pt(0, { viewCount: 1300 })];
    const out = computeDelta(points, postedLongAgo, "viewCount");
    expect(out.ok).toBe(true);
    if (out.ok) {
      expect(out.result.delta).toBe(300);
      expect(out.result.actualHoursBetween).toBeCloseTo(20, 0);
    }
  });

  it("marks insufficient_data when only recent samples exist", () => {
    const points = [pt(1, { viewCount: 100 }), pt(0, { viewCount: 200 })];
    const out = computeDelta(points, postedLongAgo, "viewCount");
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.failure.kind).toBe("insufficient_data");
  });

  it("marks insufficient_data when only far-past samples exist (e.g. 48h ago)", () => {
    const points = [pt(48, { viewCount: 100 }), pt(0, { viewCount: 500 })];
    const out = computeDelta(points, postedLongAgo, "viewCount");
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.failure.kind).toBe("insufficient_data");
  });

  it("marks too_new when post is less than 24h old", () => {
    const postedRecently = new Date(Date.now() - 12 * 3_600_000).toISOString();
    const points = [pt(10, { viewCount: 100 }), pt(0, { viewCount: 200 })];
    const out = computeDelta(points, postedRecently, "viewCount");
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.failure.kind).toBe("too_new");
  });

  it("marks no_metric when the latest observation lacks the metric", () => {
    const points = [pt(24, { viewCount: 100 }), pt(0, { viewCount: null, likeCount: 5 })];
    const out = computeDelta(points, postedLongAgo, "viewCount");
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.failure.kind).toBe("no_metric");
  });

  it("never interpolates missing points — skips null reference to find another", () => {
    const points = [
      pt(48, { viewCount: 800 }),
      pt(24, { viewCount: null }), // null at target
      pt(22, { viewCount: 900 }),
      pt(0, { viewCount: 1200 }),
    ];
    const out = computeDelta(points, postedLongAgo, "viewCount");
    expect(out.ok).toBe(true);
    if (out.ok) {
      expect(out.result.referenceValue).toBe(900); // NOT interpolated
    }
  });

  it("preserves negative delta (does not clip to 0)", () => {
    const points = [pt(24, { viewCount: 1000 }), pt(0, { viewCount: 950 })];
    const out = computeDelta(points, postedLongAgo, "viewCount");
    expect(out.ok).toBe(true);
    if (out.ok) expect(out.result.delta).toBe(-50);
  });

  it("returns insufficient_data with fewer than 2 samples", () => {
    const out = computeDelta([pt(0, { viewCount: 5 })], postedLongAgo, "viewCount");
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.failure.kind).toBe("insufficient_data");
  });
});
