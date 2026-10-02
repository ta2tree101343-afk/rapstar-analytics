import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getClient } from "../api/client";
import type { RankingType } from "../api/types";
import { RankingTabs } from "../components/RankingTabs";
import { RankingRow } from "../components/RankingRow";
import { assignRanks } from "../lib/ranking";
import { EmptyState, ErrorState, SkeletonRankingList } from "../components/EmptyState";
import { LastUpdatedLabel } from "../components/LastUpdatedLabel";

const PAGE_SIZE = 20;

export function RankingsPage() {
  const [type, setType] = useState<RankingType>("cumulative_views");
  const [displayCount, setDisplayCount] = useState(PAGE_SIZE);

  const client = getClient();
  const rankingsQuery = useQuery({
    queryKey: ["rankings", type],
    queryFn: () => client.getRankings({ type }),
  });
  const statusQuery = useQuery({
    queryKey: ["status"],
    queryFn: () => client.getStatus(),
  });

  const handleTabChange = (next: RankingType) => {
    setType(next);
    setDisplayCount(PAGE_SIZE);
  };

  return (
    <section aria-labelledby="rankings-heading" className="flex flex-col gap-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 id="rankings-heading" className="text-2xl sm:text-3xl font-bold text-fg-primary">
          応募動画ランキング
        </h1>
        <LastUpdatedLabel iso={statusQuery.data?.lastSuccessAt ?? null} />
      </div>

      <RankingTabs value={type} onChange={handleTabChange} />

      {rankingsQuery.isPending && <SkeletonRankingList />}

      {rankingsQuery.isError && (
        <ErrorState
          message="ランキングデータの取得に失敗しました。"
          onRetry={() => rankingsQuery.refetch()}
        />
      )}

      {rankingsQuery.data && rankingsQuery.data.items.length === 0 && (
        <EmptyState
          title="対象データがありません"
          hint="収集がまだ完了していないか、対象投稿がありません。"
        />
      )}

      {rankingsQuery.data && rankingsQuery.data.items.length > 0 && (() => {
        const ranked = assignRanks(rankingsQuery.data.items);
        const visible = ranked.slice(0, displayCount);
        const canLoadMore = displayCount < ranked.length;
        return (
          <>
            <div className="flex items-center justify-between text-sm text-fg-secondary">
              <div>
                対象 {rankingsQuery.data.totalEligible} 件
                <span className="mx-1.5 text-fg-muted">/</span>
                有効 {rankingsQuery.data.totalWithData} 件
              </div>
              <div className="text-xs text-fg-muted">
                {visible.length} / {ranked.length} 件を表示
              </div>
            </div>

            <div className="divide-y divide-border-subtle">
              {visible.map((item) => (
                <RankingRow key={item.postId} item={item} type={type} />
              ))}
            </div>

            {canLoadMore && (
              <div className="flex justify-center pt-2">
                <button
                  onClick={() => setDisplayCount((n) => n + PAGE_SIZE)}
                  className="rounded-md border border-border-strong bg-bg-card px-6 py-2.5 text-sm font-medium text-fg-primary hover:border-accent-yellow hover:text-accent-yellow transition-colors"
                >
                  もっと見る ({ranked.length - displayCount} 件)
                </button>
              </div>
            )}
          </>
        );
      })()}
    </section>
  );
}
