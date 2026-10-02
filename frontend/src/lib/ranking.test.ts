import { describe, it, expect } from "vitest";
import { assignRanks, sortRanking } from "./ranking";
import type { RankingItem } from "../api/types";

function mk(id: string, value: number | null, reason?: RankingItem["reason"]): RankingItem {
  return {
    postId: id,
    rapperName: id,
    permalink: `https://example.com/${id}`,
    postedAt: "2026-09-15T00:00:00Z",
    latestFetchedAt: "2026-09-20T00:00:00Z",
    value,
    valueLabel: value === null ? "—" : String(value),
    cumulative: { viewCount: null, likeCount: null, commentsCount: null },
    reason: reason ?? null,
  };
}

describe("sortRanking + assignRanks", () => {
  it("sorts descending by value and sends nulls to the bottom", () => {
    const items = [mk("a", 100), mk("b", null, "insufficient_data"), mk("c", 300), mk("d", 200)];
    const sorted = sortRanking(items, "cumulative_views");
    expect(sorted.map((i) => i.postId)).toEqual(["c", "d", "a", "b"]);
  });

  it("assigns ranks 1-based, and null values receive rank=null", () => {
    const items = [mk("c", 300), mk("d", 200), mk("a", 100), mk("b", null)];
    const ranked = assignRanks(items);
    expect(ranked.map((r) => r.rank)).toEqual([1, 2, 3, null]);
  });

  it("gives equal ranks to items with the same value", () => {
    const items = [mk("c", 300), mk("d", 300), mk("a", 100)];
    const ranked = assignRanks(items);
    expect(ranked.map((r) => r.rank)).toEqual([1, 1, 3]);
  });
});
