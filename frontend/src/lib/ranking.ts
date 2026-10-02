import type { RankingItem, RankingType } from "../api/types";

export function sortRanking(items: RankingItem[], type: RankingType): RankingItem[] {
  void type; // reserved for future custom orderings
  return [...items].sort((a, b) => {
    if (a.value === null && b.value === null) return 0;
    if (a.value === null) return 1;
    if (b.value === null) return -1;
    return b.value - a.value;
  });
}

export function assignRanks(items: RankingItem[]): Array<RankingItem & { rank: number | null }> {
  let lastValue: number | null = null;
  let lastRank = 0;
  let index = 0;
  return items.map((it) => {
    index += 1;
    if (it.value === null) return { ...it, rank: null };
    if (lastValue === it.value) {
      return { ...it, rank: lastRank };
    }
    lastValue = it.value;
    lastRank = index;
    return { ...it, rank: lastRank };
  });
}
