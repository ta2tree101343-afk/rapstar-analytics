import type { AnalyticsClient } from "../api/client";
import type {
  HistoryResponse,
  PostDetail,
  RankingItem,
  RankingResponse,
  RankingType,
  StatusResponse,
} from "../api/types";
import { MOCK_POSTS } from "./data";
import { computeDelta, type Metric } from "../lib/delta";
import { sortRanking } from "../lib/ranking";

const NETWORK_DELAY_MS = 250;

function delay<T>(v: T): Promise<T> {
  return new Promise((res) => setTimeout(() => res(v), NETWORK_DELAY_MS));
}

function metricForType(type: RankingType): Metric | null {
  switch (type) {
    case "cumulative_views":
    case "delta_views_24h":
      return "viewCount";
    case "cumulative_likes":
    case "delta_likes_24h":
      return "likeCount";
    case "cumulative_comments":
      return "commentsCount";
  }
}

function latestNonNull(post: (typeof MOCK_POSTS)[number], metric: Metric): [number | null, string | null] {
  for (let i = post.history.length - 1; i >= 0; i--) {
    const p = post.history[i];
    const v = p[metric];
    if (v !== null && v !== undefined) return [v, p.fetchedAt];
  }
  return [null, null];
}

function buildCumulativeItem(post: (typeof MOCK_POSTS)[number], metric: Metric): RankingItem {
  const [value, fetchedAt] = latestNonNull(post, metric);
  const [vc] = latestNonNull(post, "viewCount");
  const [lc] = latestNonNull(post, "likeCount");
  const [cc] = latestNonNull(post, "commentsCount");
  return {
    postId: post.postId,
    rapperName: post.rapperName,
    permalink: post.permalink,
    postedAt: post.postedAt,
    latestFetchedAt: fetchedAt,
    value,
    valueLabel: value === null ? "—" : String(value),
    cumulative: { viewCount: vc, likeCount: lc, commentsCount: cc },
    reason: value === null ? "no_metric" : null,
  };
}

function buildDeltaItem(post: (typeof MOCK_POSTS)[number], metric: Metric): RankingItem {
  const outcome = computeDelta(post.history, post.postedAt, metric);
  const [vc] = latestNonNull(post, "viewCount");
  const [lc] = latestNonNull(post, "likeCount");
  const [cc] = latestNonNull(post, "commentsCount");
  if (outcome.ok) {
    return {
      postId: post.postId,
      rapperName: post.rapperName,
      permalink: post.permalink,
      postedAt: post.postedAt,
      latestFetchedAt: outcome.result.latestFetchedAt,
      value: outcome.result.delta,
      valueLabel: String(outcome.result.delta),
      cumulative: { viewCount: vc, likeCount: lc, commentsCount: cc },
      delta: {
        referenceFetchedAt: outcome.result.referenceFetchedAt,
        actualHoursBetween: outcome.result.actualHoursBetween,
      },
      reason: null,
    };
  }
  return {
    postId: post.postId,
    rapperName: post.rapperName,
    permalink: post.permalink,
    postedAt: post.postedAt,
    latestFetchedAt: latestNonNull(post, metric)[1],
    value: null,
    valueLabel: "—",
    cumulative: { viewCount: vc, likeCount: lc, commentsCount: cc },
    delta: null,
    reason: outcome.failure.kind,
  };
}

export function createMockClient(): AnalyticsClient {
  return {
    async getStatus(): Promise<StatusResponse> {
      const entries = MOCK_POSTS.filter((p) => p.classification === "entry");
      return delay({
        lastSuccessAt: new Date().toISOString(),
        lastSuccessStatus: "success",
        entryCount: entries.length,
        updatedAt: new Date().toISOString(),
        isMock: true,
      });
    },

    async getRankings({ type }: { type: RankingType }): Promise<RankingResponse> {
      const metric = metricForType(type);
      if (!metric) throw new Error(`Unsupported ranking type: ${type}`);
      const entries = MOCK_POSTS.filter((p) => p.classification === "entry");
      const isDelta = type.startsWith("delta_");
      const items = entries.map((p) =>
        isDelta ? buildDeltaItem(p, metric) : buildCumulativeItem(p, metric),
      );
      const sorted = sortRanking(items, type);
      const totalEligible = items.length;
      const totalWithData = items.filter((i) => i.value !== null).length;
      return delay({
        type,
        items: sorted,
        totalEligible,
        totalWithData,
        totalWithoutData: totalEligible - totalWithData,
        isMock: true,
      });
    },

    async getPost(postId: string): Promise<PostDetail> {
      const post = MOCK_POSTS.find((p) => p.postId === postId);
      if (!post) throw new Error(`post not found: ${postId}`);
      const [vc, vcAt] = latestNonNull(post, "viewCount");
      const [lc, lcAt] = latestNonNull(post, "likeCount");
      const [cc, ccAt] = latestNonNull(post, "commentsCount");
      const latestFetchedAt = [vcAt, lcAt, ccAt]
        .filter((x): x is string => !!x)
        .sort()
        .pop() ?? null;
      return delay({
        postId: post.postId,
        rapperName: post.rapperName,
        permalink: post.permalink,
        postedAt: post.postedAt,
        caption: post.caption,
        classification: post.classification,
        latest: {
          viewCount: vc,
          likeCount: lc,
          commentsCount: cc,
          fetchedAt: latestFetchedAt,
        },
        isMock: true,
      });
    },

    async getPostHistory(postId: string, range: "24h" | "7d" | "all"): Promise<HistoryResponse> {
      const post = MOCK_POSTS.find((p) => p.postId === postId);
      if (!post) throw new Error(`post not found: ${postId}`);
      const now = Date.now();
      const cutoff =
        range === "24h" ? now - 24 * 3_600_000 : range === "7d" ? now - 7 * 24 * 3_600_000 : 0;
      const points = post.history.filter((p) => new Date(p.fetchedAt).getTime() >= cutoff);
      return delay({
        postId: post.postId,
        range,
        points,
        isMock: true,
      });
    },

    async getCompareData(params) {
      const { range, scope = "all", ids, metric = "viewCount" } = params;
      const entries = MOCK_POSTS.filter((p) => p.classification === "entry");
      let target = entries;
      if (scope === "top10") {
        const field: keyof (typeof entries)[number]["history"][number] = metric;
        target = [...entries]
          .filter((p) => latestNonNull(p, field as Metric)[0] !== null)
          .sort((a, b) => {
            const av = latestNonNull(a, field as Metric)[0] as number;
            const bv = latestNonNull(b, field as Metric)[0] as number;
            return bv - av;
          })
          .slice(0, 10);
      } else if (scope === "selected") {
        const wanted = new Set(ids ?? []);
        const byId = new Map(entries.map((e) => [e.postId, e]));
        target = (ids ?? []).map((i) => byId.get(i)).filter((x): x is (typeof entries)[number] => !!x && wanted.has(x.postId));
      }
      const now = Date.now();
      const cutoff =
        range === "24h" ? now - 24 * 3_600_000 : range === "7d" ? now - 7 * 24 * 3_600_000 : 0;
      const series = target.map((p) => ({
        postId: p.postId,
        rapperName: p.rapperName,
        permalink: p.permalink,
        postedAt: p.postedAt,
        points: p.history.filter((h) => new Date(h.fetchedAt).getTime() >= cutoff),
      }));
      // Synthesize collection-cycle runs from unique fetchedAt values across
      // all included series. Each cluster of measurements within a 5-minute
      // window becomes one run. Real backend does this via fetch_runs table.
      const allTimes = Array.from(
        new Set(
          series.flatMap((s) => s.points.map((p) => new Date(p.fetchedAt).getTime())),
        ),
      ).sort((a, b) => a - b);
      const runs: {
        runId: string;
        startedAt: string;
        finishedAt: string;
        status: string;
        snapshotsWritten: number;
      }[] = [];
      let clusterStart: number | null = null;
      let clusterEnd = 0;
      let clusterCount = 0;
      const GAP_MS = 5 * 60_000;
      const closeCluster = () => {
        if (clusterStart === null) return;
        runs.push({
          runId: `mock-run-${runs.length + 1}`,
          startedAt: new Date(clusterStart).toISOString(),
          finishedAt: new Date(clusterEnd).toISOString(),
          status: "success",
          snapshotsWritten: clusterCount,
        });
      };
      for (const t of allTimes) {
        if (clusterStart === null || t - clusterEnd > GAP_MS) {
          closeCluster();
          clusterStart = t;
          clusterCount = 0;
        }
        clusterEnd = t;
        clusterCount += 1;
      }
      closeCluster();
      return delay({
        range,
        series,
        totalEntries: entries.length,
        runs,
        isMock: true,
      });
    },
  };
}
