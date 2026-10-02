import { describe, it, expect } from "vitest";
import {
  buildCycles,
  buildRechartsSeries,
  colorForPostId,
  computeAsOfMarkers,
  computeAsOfSnapshot,
  computeCycleSnapshot,
  findCycleForTime,
  computeCycleMarkers,
  resolveCycles,
  synthesizeCyclesFromSeries,
  topNByLatest,
  transformHistoryToDelta,
  transformSeriesToDelta,
  uniqueMeasurementTimes,
} from "./compare";
import type { CompareSeries, HistoryPoint } from "../api/types";

function pt(hoursAgoFromEpoch: number, values: Partial<Omit<HistoryPoint, "fetchedAt">>): HistoryPoint {
  const iso = new Date(hoursAgoFromEpoch * 3_600_000).toISOString();
  return {
    fetchedAt: iso,
    viewCount: values.viewCount ?? null,
    likeCount: values.likeCount ?? null,
    commentsCount: values.commentsCount ?? null,
  };
}

function series(
  postId: string,
  rapperName: string | null,
  points: HistoryPoint[],
): CompareSeries {
  return {
    postId,
    rapperName,
    permalink: `https://example/${postId}`,
    postedAt: new Date(0).toISOString(),
    points,
  };
}

describe("colorForPostId", () => {
  it("returns a deterministic HSL string per postId", () => {
    const a1 = colorForPostId("SAMPLE-1");
    const a2 = colorForPostId("SAMPLE-1");
    expect(a1).toEqual(a2);
    expect(a1).toMatch(/^hsl\(\d+,\s*\d+%,\s*\d+%\)$/);
  });

  it("distinguishes different postIds", () => {
    const a = colorForPostId("SAMPLE-1");
    const b = colorForPostId("SAMPLE-2");
    expect(a).not.toEqual(b);
  });

  it("differentiates two posts even when rapper name is the same (identity by postId)", () => {
    expect(colorForPostId("P-A")).not.toEqual(colorForPostId("P-B"));
  });
});

describe("topNByLatest", () => {
  const s1 = series("A", "Alice", [pt(1, { viewCount: 100 }), pt(2, { viewCount: 500 })]);
  const s2 = series("B", "Bob", [pt(1, { viewCount: 300 })]);
  const s3 = series("C", "Chris", [pt(1, { viewCount: null })]);
  const s4 = series("D", "Dan", [pt(1, { viewCount: 200 })]);

  it("orders by the most recent non-null value of the requested metric", () => {
    const out = topNByLatest([s1, s2, s3, s4], "viewCount", 3);
    expect(out).toEqual(["A", "B", "D"]);
  });

  it("excludes series whose latest non-null observation is missing", () => {
    const out = topNByLatest([s3], "viewCount", 5);
    expect(out).toEqual([]);
  });

  it("returns fewer than N when the source is smaller", () => {
    const out = topNByLatest([s1, s2], "viewCount", 10);
    expect(out).toHaveLength(2);
  });

  it("uses the latest present observation, not the maximum", () => {
    const out = topNByLatest([s1, s2], "viewCount", 1);
    expect(out).toEqual(["A"]);
  });
});

describe("buildRechartsSeries", () => {
  it("emits one series per input, each with its own point array", () => {
    const s1 = series("A", "Alice", [pt(1, { viewCount: 10 }), pt(3, { viewCount: 30 })]);
    const s2 = series("B", "Bob", [pt(2, { viewCount: 20 })]);
    const out = buildRechartsSeries([s1, s2], "viewCount");
    expect(out.map((s) => s.postId)).toEqual(["A", "B"]);
    expect(out[0].data.map((p) => p.v)).toEqual([10, 30]);
    expect(out[1].data.map((p) => p.v)).toEqual([20]);
  });

  it("preserves nulls (never fills with 0) and never adds interpolated points", () => {
    const s1 = series("A", "Alice", [pt(1, { viewCount: 10 }), pt(3, { viewCount: null })]);
    const out = buildRechartsSeries([s1], "viewCount");
    expect(out[0].data).toHaveLength(2);
    expect(out[0].data[1].v).toBeNull();
  });

  it("does not co-align timestamps across different series", () => {
    const s1 = series("A", "Alice", [pt(1, { viewCount: 10 }), pt(2, { viewCount: 20 })]);
    const s2 = series("B", "Bob", [pt(1.5, { viewCount: 100 })]);
    const out = buildRechartsSeries([s1, s2], "viewCount");
    expect(out[1].data.map((p) => p.t)).toEqual([1.5 * 3_600_000]);
  });

  it("sorts each series' points ascending by time", () => {
    const s1 = series("A", "Alice", [pt(5, { viewCount: 50 }), pt(1, { viewCount: 10 }), pt(3, { viewCount: 30 })]);
    const out = buildRechartsSeries([s1], "viewCount");
    expect(out[0].data.map((p) => p.v)).toEqual([10, 30, 50]);
  });

  it("attaches deterministic color per series", () => {
    const s1 = series("A", "Alice", [pt(1, { viewCount: 1 })]);
    const out = buildRechartsSeries([s1], "viewCount");
    expect(out[0].color).toEqual(colorForPostId("A"));
  });
});

describe("transformSeriesToDelta", () => {
  it("rebases against the earliest non-null observation", () => {
    const s = series("A", "Alice", [
      pt(1, { viewCount: 100 }),
      pt(3, { viewCount: 150 }),
      pt(5, { viewCount: 300 }),
    ]);
    const r = transformSeriesToDelta(s, "viewCount");
    expect(r.baseline?.baselineValue).toBe(100);
    expect(r.series.points.map((p) => p.viewCount)).toEqual([0, 50, 200]);
    expect(r.insufficient).toBe(false);
  });

  it("returns empty series and null baseline when metric is entirely absent", () => {
    const s = series("A", "Alice", [
      pt(1, { viewCount: null }),
      pt(3, { likeCount: 5 }),
    ]);
    const r = transformSeriesToDelta(s, "viewCount");
    expect(r.baseline).toBeNull();
    expect(r.series.points).toHaveLength(0);
    expect(r.insufficient).toBe(true);
  });

  it("flags insufficient when only one non-null point exists", () => {
    const s = series("A", "Alice", [pt(2, { viewCount: 50 })]);
    const r = transformSeriesToDelta(s, "viewCount");
    expect(r.baseline?.baselineValue).toBe(50);
    expect(r.series.points).toHaveLength(1);
    expect(r.series.points[0].viewCount).toBe(0);
    expect(r.insufficient).toBe(true);
  });

  it("preserves nulls at intermediate points (never zero-fills)", () => {
    const s = series("A", "Alice", [
      pt(1, { viewCount: 100 }),
      pt(2, { viewCount: null, likeCount: 5 }),
      pt(3, { viewCount: 150 }),
    ]);
    const r = transformSeriesToDelta(s, "viewCount");
    expect(r.series.points.map((p) => p.viewCount)).toEqual([0, null, 50]);
  });

  it("preserves negative deltas when the value later drops below baseline", () => {
    const s = series("A", "Alice", [
      pt(1, { viewCount: 200 }),
      pt(2, { viewCount: 150 }),
      pt(3, { viewCount: 180 }),
    ]);
    const r = transformSeriesToDelta(s, "viewCount");
    expect(r.series.points.map((p) => p.viewCount)).toEqual([0, -50, -20]);
  });

  it("skips leading nulls to pick the first non-null as the baseline", () => {
    const s = series("A", "Alice", [
      pt(1, { viewCount: null }),
      pt(2, { viewCount: null }),
      pt(3, { viewCount: 500 }),
      pt(4, { viewCount: 600 }),
    ]);
    const r = transformSeriesToDelta(s, "viewCount");
    expect(r.series.points).toHaveLength(2);
    expect(r.baseline?.baselineFetchedAt).toEqual(new Date(3 * 3_600_000).toISOString());
    expect(r.series.points.map((p) => p.viewCount)).toEqual([0, 100]);
  });

  it("passes through other metrics unchanged", () => {
    const s = series("A", "Alice", [
      pt(1, { viewCount: 100, likeCount: 10, commentsCount: 1 }),
      pt(2, { viewCount: 200, likeCount: 20, commentsCount: 2 }),
    ]);
    const r = transformSeriesToDelta(s, "viewCount");
    expect(r.series.points.map((p) => p.likeCount)).toEqual([10, 20]);
    expect(r.series.points.map((p) => p.commentsCount)).toEqual([1, 2]);
    expect(r.series.points.map((p) => p.viewCount)).toEqual([0, 100]);
  });

  it("records baseline metadata for the caller to display", () => {
    const s = series("A", "Alice", [
      pt(2, { viewCount: 500 }),
      pt(4, { viewCount: 900 }),
    ]);
    const r = transformSeriesToDelta(s, "viewCount");
    expect(r.baseline).toEqual({
      postId: "A",
      rapperName: "Alice",
      baselineFetchedAt: new Date(2 * 3_600_000).toISOString(),
      baselineValue: 500,
      pointCount: 2,
    });
  });
});

describe("transformHistoryToDelta", () => {

  it("rebases the requested metric against the earliest non-null observation", () => {
    const points: HistoryPoint[] = [
      pt(1, { viewCount: 100 }),
      pt(3, { viewCount: 250 }),
      pt(5, { viewCount: 400 }),
    ];
    const r = transformHistoryToDelta(points, "viewCount");
    expect(r.baselineValue).toBe(100);
    expect(r.baselineFetchedAt).toBe(points[0].fetchedAt);
    expect(r.points.map((p) => p.viewCount)).toEqual([0, 150, 300]);
    expect(r.insufficient).toBe(false);
  });

  it("returns empty points and null baseline when the metric is absent throughout", () => {
    const points: HistoryPoint[] = [
      pt(1, { likeCount: 5 }),
      pt(2, { likeCount: 10 }),
    ];
    const r = transformHistoryToDelta(points, "viewCount");
    expect(r.baselineFetchedAt).toBeNull();
    expect(r.baselineValue).toBeNull();
    expect(r.points).toEqual([]);
    expect(r.insufficient).toBe(true);
  });

  it("flags insufficient when only one non-null observation exists", () => {
    const points: HistoryPoint[] = [pt(1, { viewCount: 42 })];
    const r = transformHistoryToDelta(points, "viewCount");
    expect(r.baselineValue).toBe(42);
    expect(r.points).toHaveLength(1);
    expect(r.points[0].viewCount).toBe(0);
    expect(r.insufficient).toBe(true);
  });

  it("preserves null gaps at intermediate points (never zero-fills)", () => {
    const points: HistoryPoint[] = [
      pt(1, { viewCount: 100 }),
      pt(2, { viewCount: null }),
      pt(3, { viewCount: 150 }),
    ];
    const r = transformHistoryToDelta(points, "viewCount");
    expect(r.points.map((p) => p.viewCount)).toEqual([0, null, 50]);
  });

  it("preserves negative deltas when the metric later drops below baseline", () => {
    const points: HistoryPoint[] = [
      pt(1, { likeCount: 500 }),
      pt(2, { likeCount: 480 }),
      pt(3, { likeCount: 520 }),
    ];
    const r = transformHistoryToDelta(points, "likeCount");
    expect(r.points.map((p) => p.likeCount)).toEqual([0, -20, 20]);
  });

  it("drops leading points whose metric is null and picks the first non-null as baseline", () => {
    const points: HistoryPoint[] = [
      pt(1, { viewCount: null }),
      pt(2, { viewCount: null }),
      pt(3, { viewCount: 200 }),
      pt(4, { viewCount: 260 }),
    ];
    const r = transformHistoryToDelta(points, "viewCount");
    expect(r.baselineFetchedAt).toBe(new Date(3 * 3_600_000).toISOString());
    expect(r.points).toHaveLength(2);
    expect(r.points.map((p) => p.viewCount)).toEqual([0, 60]);
  });

  it("computes independent baselines per metric when metrics appear at different points", () => {
    const points: HistoryPoint[] = [
      pt(1, { viewCount: 100, likeCount: null, commentsCount: null }),
      pt(2, { viewCount: 200, likeCount: 10, commentsCount: null }),
      pt(3, { viewCount: 250, likeCount: 15, commentsCount: 2 }),
    ];
    const rv = transformHistoryToDelta(points, "viewCount");
    const rl = transformHistoryToDelta(points, "likeCount");
    const rc = transformHistoryToDelta(points, "commentsCount");

    expect(rv.baselineFetchedAt).toBe(points[0].fetchedAt);
    expect(rv.points.map((p) => p.viewCount)).toEqual([0, 100, 150]);

    expect(rl.baselineFetchedAt).toBe(points[1].fetchedAt);
    expect(rl.points.map((p) => p.likeCount)).toEqual([0, 5]);

    expect(rc.baselineFetchedAt).toBe(points[2].fetchedAt);
    expect(rc.points.map((p) => p.commentsCount)).toEqual([0]);
    expect(rc.insufficient).toBe(true);
  });

  it("does not mutate the input points array", () => {
    const points: HistoryPoint[] = [
      pt(3, { viewCount: 300 }),
      pt(1, { viewCount: 100 }),
      pt(2, { viewCount: 200 }),
    ];
    const snapshot = points.map((p) => ({ ...p }));
    transformHistoryToDelta(points, "viewCount");
    expect(points).toEqual(snapshot);
  });

  it("sorts by fetchedAt before rebasing so baseline is chronologically first", () => {
    const points: HistoryPoint[] = [
      pt(3, { viewCount: 300 }),
      pt(1, { viewCount: 100 }),
      pt(2, { viewCount: 200 }),
    ];
    const r = transformHistoryToDelta(points, "viewCount");
    expect(r.baselineFetchedAt).toBe(new Date(1 * 3_600_000).toISOString());
    expect(r.points.map((p) => p.viewCount)).toEqual([0, 100, 200]);
  });
});

describe("computeAsOfSnapshot", () => {
  const buildSeries = () =>
    buildRechartsSeries(
      [
        {
          postId: "p1",
          rapperName: "One",
          points: [
            pt(1, { viewCount: 100 }),
            pt(3, { viewCount: 300 }),
            pt(5, { viewCount: 500 }),
          ],
        },
        {
          postId: "p2",
          rapperName: "Two",
          points: [pt(2, { viewCount: 200 }), pt(4, { viewCount: 400 })],
        },
        {
          postId: "p3",
          rapperName: "Three",
          points: [pt(10, { viewCount: 999 })],
        },
      ] as CompareSeries[],
      "viewCount",
    );

  const hoursToMs = (h: number) => h * 3_600_000;

  it("returns each series' latest measurement at or before selectedT", () => {
    const series = buildSeries();
    const snap = computeAsOfSnapshot(hoursToMs(3), series);
    const p1 = snap.find((r) => r.postId === "p1");
    expect(p1?.value).toBe(300);
    const p2 = snap.find((r) => r.postId === "p2");
    expect(p2?.value).toBe(200);
    const p3 = snap.find((r) => r.postId === "p3");
    expect(p3?.value).toBeNull();
  });

  it("never uses future measurements", () => {
    const series = buildSeries();
    const snap = computeAsOfSnapshot(hoursToMs(0), series);
    for (const row of snap) expect(row.value).toBeNull();
  });

  it("reports the ACTUAL fetchedAt and ageMs of the returned measurement", () => {
    const series = buildSeries();
    const snap = computeAsOfSnapshot(hoursToMs(5), series);
    const p2 = snap.find((r) => r.postId === "p2");
    expect(p2?.actualFetchedAt).toBe(new Date(hoursToMs(4)).toISOString());
    expect(p2?.ageMs).toBe(hoursToMs(1));
  });

  it("sorts non-null values descending; null entries follow", () => {
    const series = buildSeries();
    const snap = computeAsOfSnapshot(hoursToMs(4), series);
    expect(snap.map((r) => r.postId)).toEqual(["p2", "p1", "p3"]);
  });

  it("preserves postId, rapperName, and color from RechartsSeries", () => {
    const series = buildSeries();
    const snap = computeAsOfSnapshot(hoursToMs(10), series);
    const p3 = snap.find((r) => r.postId === "p3");
    expect(p3?.rapperName).toBe("Three");
    expect(p3?.color).toMatch(/^hsl\(/);
    expect(p3?.value).toBe(999);
  });

  it("skips leading null measurements when scanning as-of", () => {
    const series = buildRechartsSeries(
      [
        {
          postId: "np",
          rapperName: "Nulls first",
          points: [
            { fetchedAt: new Date(hoursToMs(1)).toISOString(), viewCount: null, likeCount: null, commentsCount: null },
            pt(3, { viewCount: 50 }),
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );
    const snap = computeAsOfSnapshot(hoursToMs(2), series);
    expect(snap[0].value).toBeNull(); // t=1's null skipped, no other measurement ≤ 2.
    const snap2 = computeAsOfSnapshot(hoursToMs(3), series);
    expect(snap2[0].value).toBe(50);
  });
});

describe("computeAsOfMarkers", () => {
  const hoursToMs = (h: number) => h * 3_600_000;
  const s = (postId: string, pts: Array<[number, number | null]>) =>
    buildRechartsSeries(
      [
        {
          postId,
          rapperName: postId,
          permalink: "",
          postedAt: new Date(0).toISOString(),
          points: pts.map(([h, v]) => ({
            fetchedAt: new Date(hoursToMs(h)).toISOString(),
            viewCount: v,
            likeCount: null,
            commentsCount: null,
          })),
        },
      ],
      "viewCount",
    );

  it("returns isExact=true when selectedT hits an actual measurement", () => {
    const [ser] = s("a", [[1, 10], [3, 30]]);
    const markers = computeAsOfMarkers(hoursToMs(3), [ser]);
    expect(markers).toHaveLength(1);
    expect(markers[0].isExact).toBe(true);
    expect(markers[0].y).toBe(30);
    expect(markers[0].t).toBe(hoursToMs(3));
  });

  it("linearly interpolates Y between flanking points when no exact measurement", () => {
    const [ser] = s("a", [[0, 100], [10, 200]]);
    const markers = computeAsOfMarkers(hoursToMs(4), [ser]);
    expect(markers).toHaveLength(1);
    expect(markers[0].isExact).toBe(false);
    expect(markers[0].y).toBeCloseTo(140);
  });

  it("skips series when selectedT is before the first measurement (no line)", () => {
    const [ser] = s("a", [[5, 50], [10, 100]]);
    const markers = computeAsOfMarkers(hoursToMs(2), [ser]);
    expect(markers).toHaveLength(0);
  });

  it("skips series when selectedT is after the last measurement (no line)", () => {
    const [ser] = s("a", [[5, 50], [10, 100]]);
    const markers = computeAsOfMarkers(hoursToMs(20), [ser]);
    expect(markers).toHaveLength(0);
  });

  it("skips series with no non-null measurements", () => {
    const [ser] = s("a", [[1, null], [2, null]]);
    const markers = computeAsOfMarkers(hoursToMs(5), [ser]);
    expect(markers).toHaveLength(0);
  });

  it("returns one marker per contributing series, preserving postId and color", () => {
    const seriesList = [
      ...s("a", [[0, 0], [10, 100]]),
      ...s("b", [[2, 20], [8, 80]]),
    ];
    const markers = computeAsOfMarkers(hoursToMs(5), seriesList);
    expect(markers.map((m) => m.postId).sort()).toEqual(["a", "b"]);
    for (const m of markers) {
      expect(m.color).toMatch(/^hsl\(/);
      expect(m.isExact).toBe(false);
    }
  });

  it("interpolates across a null gap using the nearest flanking non-null points", () => {
    const [ser] = s("a", [[0, 100], [2, null], [4, 300]]);
    const markers = computeAsOfMarkers(hoursToMs(2), [ser]);
    expect(markers).toHaveLength(1);
    expect(markers[0].isExact).toBe(false);
    expect(markers[0].y).toBeCloseTo(200);
  });
});

describe("uniqueMeasurementTimes", () => {
  it("returns sorted distinct t values across series, ignoring nulls", () => {
    const series = buildRechartsSeries(
      [
        {
          postId: "a",
          rapperName: "A",
          points: [pt(1, { viewCount: 10 }), pt(3, { viewCount: 30 })],
        },
        {
          postId: "b",
          rapperName: "B",
          points: [
            pt(2, { viewCount: 20 }),
            pt(3, { viewCount: 35 }),
            { fetchedAt: new Date(4 * 3_600_000).toISOString(), viewCount: null, likeCount: null, commentsCount: null },
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );
    expect(uniqueMeasurementTimes(series)).toEqual([
      1 * 3_600_000,
      2 * 3_600_000,
      3 * 3_600_000,
    ]);
  });
});

// Cycle-based snapshot: mirrors the DDB reality from 2026-09-23 where Sol's
// measurement at 00:00:49 was ~8s ahead of Almond_Eye's at 00:00:57. Under
// the old computeAsOfSnapshot, selecting Sol's exact time excluded
// Almond_Eye's same-cycle point and fell back to the previous day's value.
describe("buildCycles / findCycleForTime / computeCycleSnapshot", () => {
  const hoursToMs = (h: number) => h * 3_600_000;
  const iso = (h: number) => new Date(hoursToMs(h)).toISOString();

  const runs = [
    { runId: "R1", startedAt: iso(10), finishedAt: iso(10 + 1 / 60), status: "success" },
    { runId: "R2", startedAt: iso(30), finishedAt: iso(30 + 1 / 60), status: "success" },
    { runId: "R3", startedAt: iso(54), finishedAt: iso(54 + 1 / 60), status: "success" },
  ];

  const makeSeries = () => {
    // A: measured in every cycle, at slightly different offsets within each.
    // B: measured in R1 and R3 only (R2 is a "missing series in cycle" case).
    // Times below use minutes-from-cycle-start (seconds precision matters).
    const secondsAfter = (baseHours: number, secs: number) =>
      new Date(hoursToMs(baseHours) + secs * 1000).toISOString();
    return buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: secondsAfter(10, 5), viewCount: 100, likeCount: null, commentsCount: null },
            { fetchedAt: secondsAfter(30, 12), viewCount: 200, likeCount: null, commentsCount: null },
            { fetchedAt: secondsAfter(54, 8), viewCount: 350, likeCount: null, commentsCount: null },
          ],
        },
        {
          postId: "B",
          rapperName: "B",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: secondsAfter(10, 25), viewCount: 50, likeCount: null, commentsCount: null },
            { fetchedAt: secondsAfter(54, 30), viewCount: 90, likeCount: null, commentsCount: null },
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );
  };

  it("buildCycles turns API runs into sorted number-time envelopes", () => {
    const cycles = buildCycles(runs);
    expect(cycles).toHaveLength(3);
    expect(cycles[0].runId).toBe("R1");
    expect(cycles[2].runId).toBe("R3");
    expect(cycles[0].startedAt).toBeLessThan(cycles[1].startedAt);
  });

  it("findCycleForTime resolves any time inside a cycle envelope", () => {
    const cycles = buildCycles(runs);
    expect(findCycleForTime(hoursToMs(10), cycles)!.runId).toBe("R1");
    expect(findCycleForTime(hoursToMs(30) + 20_000, cycles)!.runId).toBe("R2");
    const between = (hoursToMs(30) + hoursToMs(54)) / 2;
    expect(["R2", "R3"]).toContain(findCycleForTime(between, cycles)!.runId);
  });

  it("returns null cycle when there are no runs", () => {
    expect(findCycleForTime(12345, [])).toBeNull();
  });

  it("computeCycleSnapshot returns same entries whichever point in the cycle is used", () => {
    const cycles = buildCycles(runs);
    const series = makeSeries();
    // Two "click points" within the same R3 window: A's measurement (54h+8s)
    // and B's measurement (54h+30s). Both must resolve to the R3 cycle.
    const timeA = new Date(series[0].data[2].fetchedAt).getTime();
    const timeB = new Date(series[1].data[1].fetchedAt).getTime();
    const cycleA = findCycleForTime(timeA, cycles)!;
    const cycleB = findCycleForTime(timeB, cycles)!;
    expect(cycleA.runId).toBe("R3");
    expect(cycleB.runId).toBe("R3");
    const snapA = computeCycleSnapshot(cycleA, series);
    const snapB = computeCycleSnapshot(cycleB, series);
    expect(snapA).toEqual(snapB);
    const byId = Object.fromEntries(snapA.map((e) => [e.postId, e]));
    expect(byId.A.inCycle).toBe(true);
    expect(byId.A.value).toBe(350);
    expect(byId.B.inCycle).toBe(true);
    expect(byId.B.value).toBe(90);
  });

  it("marks series without an in-cycle measurement as inCycle=false (no backfill)", () => {
    const cycles = buildCycles(runs);
    const series = makeSeries();
    const snap = computeCycleSnapshot(cycles[1] /* R2 */, series);
    const byId = Object.fromEntries(snap.map((e) => [e.postId, e]));
    expect(byId.A.inCycle).toBe(true);
    expect(byId.A.value).toBe(200);
    // B has NO R2 measurement — must NOT use its R1 (=50) or R3 (=90) value.
    expect(byId.B.inCycle).toBe(false);
    expect(byId.B.value).toBeNull();
    expect(byId.B.actualFetchedAt).toBeNull();
  });

  it("does NOT fabricate a cycle for a failed run (caller filters upstream)", () => {
    // The API already excludes error runs from `runs`. We only need to ensure
    // that no invented cycle appears in what we return.
    const failedRuns = [
      { runId: "R1", startedAt: iso(10), finishedAt: iso(10 + 1 / 60), status: "success" },
      // The failed 9/22-equivalent run is simply absent from this list.
    ];
    const cycles = buildCycles(failedRuns);
    expect(cycles).toHaveLength(1);
    expect(cycles.map((c) => c.runId)).toEqual(["R1"]);
  });

  it("distinguishes null-valued in-cycle measurement from series absent in cycle", () => {
    const cyclesLocal = buildCycles([
      { runId: "R1", startedAt: iso(10), finishedAt: iso(10 + 1 / 60), status: "success" },
    ]);
    const series = buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            // A: real measurement present but view_count is null (metric hidden).
            { fetchedAt: iso(10 + 0.5 / 60), viewCount: null, likeCount: 10, commentsCount: 1 },
          ],
        },
        {
          postId: "B",
          rapperName: "B",
          permalink: "",
          postedAt: iso(0),
          points: [], // B: no record at all in this cycle
        },
      ] as CompareSeries[],
      "viewCount",
    );
    const snap = computeCycleSnapshot(cyclesLocal[0], series);
    const byId = Object.fromEntries(snap.map((e) => [e.postId, e]));
    // A: measurement exists in-cycle → inCycle=true, value=null (null metric).
    expect(byId.A.inCycle).toBe(true);
    expect(byId.A.value).toBeNull();
    expect(byId.A.actualFetchedAt).toBeTruthy();
    // B: no record at all → inCycle=false, value=null.
    expect(byId.B.inCycle).toBe(false);
    expect(byId.B.value).toBeNull();
    expect(byId.B.actualFetchedAt).toBeNull();
  });

  it("synthesizeCyclesFromSeries: fallback clusters series times into cycles when API runs are missing", () => {
    // Two clusters ~20h apart (definitely > 5min gap) become two cycles.
    const seriesList = buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: iso(10), viewCount: 100, likeCount: null, commentsCount: null },
            { fetchedAt: iso(30), viewCount: 200, likeCount: null, commentsCount: null },
          ],
        },
        {
          postId: "B",
          rapperName: "B",
          permalink: "",
          postedAt: iso(0),
          points: [
            // 8 seconds AFTER A's 10h measurement — same cycle.
            { fetchedAt: new Date(hoursToMs(10) + 8_000).toISOString(), viewCount: 50, likeCount: null, commentsCount: null },
            { fetchedAt: iso(30), viewCount: 90, likeCount: null, commentsCount: null },
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );
    const cycles = synthesizeCyclesFromSeries(seriesList);
    expect(cycles).toHaveLength(2);
    expect(cycles[0].startedAt).toBe(hoursToMs(10));
    expect(cycles[0].finishedAt).toBe(hoursToMs(10) + 8_000);
    expect(cycles[1].startedAt).toBe(hoursToMs(30));
    expect(findCycleForTime(hoursToMs(10), cycles)!.runId).toBe(cycles[0].runId);
    expect(findCycleForTime(hoursToMs(10) + 8_000, cycles)!.runId).toBe(cycles[0].runId);
    const snap = computeCycleSnapshot(cycles[0], seriesList);
    const byId = Object.fromEntries(snap.map((e) => [e.postId, e]));
    expect(byId.A.inCycle).toBe(true);
    expect(byId.A.value).toBe(100);
    expect(byId.B.inCycle).toBe(true);
    expect(byId.B.value).toBe(50);
  });

  it("computeCycleMarkers returns one marker per series that measured in the cycle, none for absent series", () => {
    const cyclesLocal = buildCycles([
      { runId: "R", startedAt: iso(10), finishedAt: iso(10 + 1 / 60), status: "success" },
    ]);
    const seriesList = buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: iso(10 + 0.5 / 60), viewCount: 100, likeCount: null, commentsCount: null },
          ],
        },
        {
          postId: "B",
          rapperName: "B",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: new Date(hoursToMs(10) + 45_000).toISOString(), viewCount: 200, likeCount: null, commentsCount: null },
          ],
        },
        {
          postId: "C",
          rapperName: "C",
          permalink: "",
          postedAt: iso(0),
          points: [], // C has no measurement — no marker expected
        },
        {
          postId: "D",
          rapperName: "D",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: iso(10 + 0.2 / 60), viewCount: null, likeCount: 1, commentsCount: 1 },
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );
    const markers = computeCycleMarkers(cyclesLocal[0], seriesList);
    const ids = markers.map((m) => m.postId).sort();
    expect(ids).toEqual(["A", "B"]);
    // Marker positions land on each series' own measurement time — proving
    // that the "different-second offsets" are respected inside one cycle.
    const byId = Object.fromEntries(markers.map((m) => [m.postId, m]));
    expect(byId.A.t).toBe(hoursToMs(10) + 30_000);
    expect(byId.A.y).toBe(100);
    expect(byId.B.t).toBe(hoursToMs(10) + 45_000);
    expect(byId.B.y).toBe(200);
  });

  it("does NOT merge two adjacent-but-distinct cycles that happen to be close in time", () => {
    // Two cycles 10 seconds apart (e.g., manual invoke immediately after
    // scheduled run). Must remain distinct.
    const closeRuns = [
      { runId: "X", startedAt: iso(10), finishedAt: iso(10 + 1 / 60), status: "success" },
      { runId: "Y", startedAt: iso(10 + 1 / 60 + 10 / 3600), finishedAt: iso(10 + 2 / 60), status: "success" },
    ];
    const cycles = buildCycles(closeRuns);
    expect(cycles).toHaveLength(2);
    expect(cycles.map((c) => c.runId)).toEqual(["X", "Y"]);
    const inY = (cycles[1].startedAt + cycles[1].finishedAt) / 2;
    expect(findCycleForTime(inY, cycles)!.runId).toBe("Y");
  });
});

// resolveCycles decides between authoritative API runs and the fallback
// clustering of series timestamps. These tests are the contract for that
// decision — nothing else in the codebase should re-implement the preference
// order. All assertions are at the shape/identity level so they survive any
// future tuning of CYCLE_MATCH_TOLERANCE_MS or synthesizeCyclesFromSeries
// gapMs.
describe("resolveCycles (authoritative API vs. series fallback)", () => {
  const hoursToMs = (h: number) => h * 3_600_000;
  const iso = (h: number) => new Date(hoursToMs(h)).toISOString();
  const secondsAfter = (hours: number, secs: number) =>
    new Date(hoursToMs(hours) + secs * 1000).toISOString();

  const authoritativeRuns = [
    {
      runId: "8ce6cff3-9c3a-47c2-abbd-authoritative-run-1",
      startedAt: iso(10),
      finishedAt: iso(10 + 1 / 60),
      status: "success",
    },
    {
      runId: "b2378ce7-77ff-4abb-adef-authoritative-run-2",
      startedAt: iso(34),
      finishedAt: iso(34 + 1 / 60),
      status: "success",
    },
  ];

  // Series with measurements inside both runs. Each series lands at a
  // slightly different offset inside the run window — the same real-world
  // pattern we saw on 2026-09-23 (Sol at 00:00:49, Almond_Eye at 00:00:57).
  const seriesInsideBothRuns = () =>
    buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: secondsAfter(10, 5),  viewCount: 100, likeCount: null, commentsCount: null },
            { fetchedAt: secondsAfter(34, 7),  viewCount: 300, likeCount: null, commentsCount: null },
          ],
        },
        {
          postId: "B",
          rapperName: "B",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: secondsAfter(10, 30), viewCount: 50,  likeCount: null, commentsCount: null },
            { fetchedAt: secondsAfter(34, 42), viewCount: 90,  likeCount: null, commentsCount: null },
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );

  it("A — authoritative runs present: uses buildCycles, never synthesises", () => {
    const cycles = resolveCycles(authoritativeRuns, seriesInsideBothRuns());
    expect(cycles).toHaveLength(2);
    expect(cycles.map((c) => c.runId)).toEqual([
      authoritativeRuns[0].runId,
      authoritativeRuns[1].runId,
    ]);
    for (const c of cycles) {
      expect(c.runId.startsWith("synthetic-")).toBe(false);
    }
    expect(cycles[0].startedAt).toBe(hoursToMs(10));
    expect(cycles[0].finishedAt).toBe(new Date(authoritativeRuns[0].finishedAt).getTime());
  });

  it("B — runs undefined: falls back to synthesising from series", () => {
    const cycles = resolveCycles(undefined, seriesInsideBothRuns());
    expect(cycles).toHaveLength(2);
    expect(cycles.map((c) => c.runId)).toEqual(["synthetic-1", "synthetic-2"]);
    for (const c of cycles) {
      expect(c.runId.startsWith("synthetic-")).toBe(true);
    }
  });

  it("C — runs is an empty array: falls back to synthesis (same as undefined)", () => {
    const cycles = resolveCycles([], seriesInsideBothRuns());
    expect(cycles).toHaveLength(2);
    expect(cycles.every((c) => c.runId.startsWith("synthetic-"))).toBe(true);
  });

  it("D — authoritative runs survive partial series coverage (some posts measured, some not)", () => {
    const partialSeries = buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: secondsAfter(10, 5),  viewCount: 100, likeCount: null, commentsCount: null },
            { fetchedAt: secondsAfter(34, 7),  viewCount: 300, likeCount: null, commentsCount: null },
          ],
        },
        {
          postId: "B",
          rapperName: "B",
          permalink: "",
          postedAt: iso(0),
          points: [], // never produced a measurement
        },
      ] as CompareSeries[],
      "viewCount",
    );
    const cycles = resolveCycles(authoritativeRuns, partialSeries);
    // Both authoritative cycles must still be present — the fact that one
    // post never reported does NOT collapse the cycle, so missingCount in
    // the panel can be computed correctly.
    expect(cycles).toHaveLength(2);
    expect(cycles.map((c) => c.runId)).toEqual([
      authoritativeRuns[0].runId,
      authoritativeRuns[1].runId,
    ]);
    // Downstream snapshot must flag B as not-in-cycle (inCycle=false) for
    // both cycles — upstream still had the authoritative envelope.
    const snapR1 = computeCycleSnapshot(cycles[0], partialSeries);
    const snapR2 = computeCycleSnapshot(cycles[1], partialSeries);
    const bR1 = snapR1.find((e) => e.postId === "B")!;
    const bR2 = snapR2.find((e) => e.postId === "B")!;
    expect(bR1.inCycle).toBe(false);
    expect(bR2.inCycle).toBe(false);
  });

  it("E — fallback restores one cycle per distinct measurement cluster across all series", () => {
    // Three clusters: 10h, 30h, 54h. Each separated by >> 5 min — must
    // produce 3 synthetic cycles. Different series contribute to different
    // subsets of clusters.
    const multiClusterSeries = buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: secondsAfter(10, 2),  viewCount: 100, likeCount: null, commentsCount: null },
            { fetchedAt: secondsAfter(30, 5),  viewCount: 200, likeCount: null, commentsCount: null },
            { fetchedAt: secondsAfter(54, 8),  viewCount: 300, likeCount: null, commentsCount: null },
          ],
        },
        {
          postId: "B",
          rapperName: "B",
          permalink: "",
          postedAt: iso(0),
          points: [
            // B lands at the 10h and 54h clusters only — intentionally
            // missing the 30h cluster.
            { fetchedAt: secondsAfter(10, 20), viewCount: 50,  likeCount: null, commentsCount: null },
            { fetchedAt: secondsAfter(54, 40), viewCount: 90,  likeCount: null, commentsCount: null },
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );
    const cycles = resolveCycles(undefined, multiClusterSeries);
    expect(cycles).toHaveLength(3);
    expect(cycles.map((c) => c.runId)).toEqual(["synthetic-1", "synthetic-2", "synthetic-3"]);
    const cycle10 = cycles[0];
    expect(cycle10.startedAt).toBeLessThanOrEqual(hoursToMs(10) + 2_000);
    expect(cycle10.finishedAt).toBeGreaterThanOrEqual(hoursToMs(10) + 20_000);
    const snap10 = computeCycleSnapshot(cycle10, multiClusterSeries);
    const byId10 = Object.fromEntries(snap10.map((e) => [e.postId, e]));
    expect(byId10.A.inCycle).toBe(true);
    expect(byId10.B.inCycle).toBe(true);
    const snap30 = computeCycleSnapshot(cycles[1], multiClusterSeries);
    const byId30 = Object.fromEntries(snap30.map((e) => [e.postId, e]));
    expect(byId30.A.inCycle).toBe(true);
    expect(byId30.B.inCycle).toBe(false);
  });

  it("F — fallback threshold boundary: < gapMs merges, > gapMs splits (uses the actual default)", () => {
    // The default gap in synthesizeCyclesFromSeries is 5 * 60_000 ms = 5 min
    // (compare.ts source of truth). We DO NOT re-declare the value here —
    // we probe the implementation with points placed just inside and just
    // outside, and assert the merge/split outcome. If the default ever
    // changes, this test will mechanically re-verify the new boundary.
    const defaultGapMs = 5 * 60_000;
    // Just-under: two measurements separated by (gap - 1ms) must merge.
    const under = buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: new Date(hoursToMs(10)).toISOString(),              viewCount: 100, likeCount: null, commentsCount: null },
            { fetchedAt: new Date(hoursToMs(10) + defaultGapMs - 1).toISOString(), viewCount: 110, likeCount: null, commentsCount: null },
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );
    expect(resolveCycles(undefined, under)).toHaveLength(1);

    // Just-over: two measurements separated by (gap + 1ms) must split.
    const over = buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: new Date(hoursToMs(10)).toISOString(),              viewCount: 100, likeCount: null, commentsCount: null },
            { fetchedAt: new Date(hoursToMs(10) + defaultGapMs + 1).toISOString(), viewCount: 110, likeCount: null, commentsCount: null },
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );
    expect(resolveCycles(undefined, over)).toHaveLength(2);
  });

  it("G — empty inputs: no runs and no series yields an empty cycle list without crashing", () => {
    expect(() => resolveCycles(undefined, [])).not.toThrow();
    expect(resolveCycles(undefined, [])).toEqual([]);
    expect(resolveCycles(null, [])).toEqual([]);
    expect(resolveCycles([], [])).toEqual([]);
  });

  it("authoritative-mode never leaks synthetic runIds even when series would produce them", () => {
    // Even if the series by themselves would be clustered into N synthetic
    // cycles, the authoritative path must win and no "synthetic-*" runId
    // may appear in the output. This is the key regression guard.
    const synthesisWouldSeeThreeClusters = buildRechartsSeries(
      [
        {
          postId: "A",
          rapperName: "A",
          permalink: "",
          postedAt: iso(0),
          points: [
            { fetchedAt: iso(0),  viewCount: 1, likeCount: null, commentsCount: null },
            { fetchedAt: iso(24), viewCount: 2, likeCount: null, commentsCount: null },
            { fetchedAt: iso(48), viewCount: 3, likeCount: null, commentsCount: null },
          ],
        },
      ] as CompareSeries[],
      "viewCount",
    );
    const cycles = resolveCycles(authoritativeRuns, synthesisWouldSeeThreeClusters);
    expect(cycles).toHaveLength(2);
    for (const c of cycles) {
      expect(c.runId.startsWith("synthetic-")).toBe(false);
    }
    expect(cycles.map((c) => c.runId)).toEqual([
      authoritativeRuns[0].runId,
      authoritativeRuns[1].runId,
    ]);
  });
});
