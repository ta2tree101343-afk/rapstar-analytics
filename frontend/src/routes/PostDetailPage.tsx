import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getClient } from "../api/client";
import { formatIsoToJst, formatNumber } from "../lib/formatters";
import { TimeSeriesChart } from "../components/TimeSeriesChart";
import { EmptyState, ErrorState } from "../components/EmptyState";
import { clsx } from "clsx";
import type { HistoryPoint } from "../api/types";
import {
  METRIC_LABEL,
  transformHistoryToDelta,
  type CompareMetric,
  type HistoryDeltaResult,
} from "../lib/compare";

type Range = "24h" | "7d" | "all";
type DisplayMode = "cumulative" | "delta";

const RANGE_LABELS: Record<Range, string> = {
  "24h": "過去24時間",
  "7d": "過去7日",
  "all": "全期間",
};

const DISPLAY_MODE_LABEL: Record<DisplayMode, string> = {
  cumulative: "累計値",
  delta: "増加数",
};

const METRIC_ORDER: CompareMetric[] = ["viewCount", "likeCount", "commentsCount"];
const METRIC_COLOR: Record<CompareMetric, string> = {
  viewCount: "#E9E9EE",
  likeCount: "#8A6BFF",
  commentsCount: "#F5B301",
};

function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number | null;
  color?: string;
}) {
  return (
    <div className="py-1">
      <div className="text-xs uppercase tracking-wider text-fg-secondary">{label}</div>
      <div
        className={clsx("mt-1 tnum text-2xl sm:text-3xl font-bold tracking-tight")}
        style={color ? { color } : undefined}
      >
        {formatNumber(value)}
      </div>
    </div>
  );
}

export function PostDetailPage() {
  const { postId } = useParams<{ postId: string }>();
  const [range, setRange] = useState<Range>("7d");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("cumulative");
  const client = getClient();

  const postQuery = useQuery({
    queryKey: ["post", postId],
    queryFn: () => client.getPost(postId!),
    enabled: !!postId,
  });
  const historyQuery = useQuery({
    queryKey: ["post-history", postId, range],
    queryFn: () => client.getPostHistory(postId!, range),
    enabled: !!postId,
  });

  if (!postId) return <ErrorState message="投稿IDが指定されていません" />;

  if (postQuery.isPending) {
    return <div className="text-fg-muted">読み込み中…</div>;
  }
  if (postQuery.isError || !postQuery.data) {
    return (
      <ErrorState
        message="投稿情報の取得に失敗しました。"
        onRetry={() => postQuery.refetch()}
      />
    );
  }

  const post = postQuery.data;

  return (
    <section className="flex flex-col gap-6">
      <div>
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm text-fg-secondary hover:text-fg-primary"
        >
          ← ランキングへ戻る
        </Link>
        <h1 className="mt-3 text-2xl sm:text-3xl font-bold">{post.rapperName ?? "(名前未取得)"}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-fg-secondary">
          <span>投稿日時: <span className="tnum">{formatIsoToJst(post.postedAt)}</span></span>
          <span>最終取得: <span className="tnum">{formatIsoToJst(post.latest.fetchedAt)}</span></span>
          <a
            href={post.permalink}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-yellow hover:underline"
          >
            Instagram で見る ↗
          </a>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-8 border-t border-border-subtle pt-4">
        <MetricCard label="再生数" value={post.latest.viewCount} />
        <MetricCard label="いいね数" value={post.latest.likeCount} color="#8A6BFF" />
        <MetricCard label="コメント数" value={post.latest.commentsCount} color="#F5B301" />
      </div>

      <div className="flex flex-wrap gap-2">
        <div
          role="tablist"
          aria-label="表示モード"
          className="inline-flex rounded-lg border border-border-strong bg-bg-card p-1"
        >
          {(["cumulative", "delta"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={displayMode === m}
              onClick={() => setDisplayMode(m)}
              className={clsx(
                "min-h-[44px] rounded-md px-3 py-2 text-sm font-medium transition-colors whitespace-nowrap",
                displayMode === m
                  ? "bg-bg-base text-fg-primary"
                  : "text-fg-secondary hover:text-fg-primary",
              )}
            >
              {DISPLAY_MODE_LABEL[m]}
            </button>
          ))}
        </div>

        <div
          role="radiogroup"
          aria-label="表示期間"
          className="inline-flex rounded-lg border border-border-strong bg-bg-card p-1"
        >
          {(Object.keys(RANGE_LABELS) as Range[]).map((r) => (
            <button
              key={r}
              role="radio"
              aria-checked={range === r}
              onClick={() => setRange(r)}
              className={clsx(
                "min-h-[44px] rounded-md px-3 py-2 text-sm font-medium transition-colors whitespace-nowrap",
                range === r
                  ? "bg-bg-base text-fg-primary"
                  : "text-fg-secondary hover:text-fg-primary",
              )}
            >
              {RANGE_LABELS[r]}
            </button>
          ))}
        </div>
      </div>

      {historyQuery.isPending && <div className="text-fg-muted">グラフを読み込み中…</div>}
      {historyQuery.isError && (
        <ErrorState message="時系列データの取得に失敗しました。" onRetry={() => historyQuery.refetch()} />
      )}
      {historyQuery.data && historyQuery.data.points.length === 0 && (
        <EmptyState
          title="この期間の取得データがありません"
          hint="収集がまだ実施されていない期間、または欠測です。実測点がない部分を補完表示することはしません。"
        />
      )}

      {historyQuery.data && historyQuery.data.points.length > 0 && (
        <DetailCharts
          points={historyQuery.data.points}
          displayMode={displayMode}
        />
      )}
    </section>
  );
}

interface MetricPresentation {
  metric: CompareMetric;
  label: string;
  color: string;
  delta: HistoryDeltaResult;
}

function DetailCharts({
  points,
  displayMode,
}: {
  points: HistoryPoint[];
  displayMode: DisplayMode;
}) {
  const presentations: MetricPresentation[] = METRIC_ORDER.map((metric) => ({
    metric,
    label:
      displayMode === "delta"
        ? `${METRIC_LABEL[metric]} の増加数`
        : `${METRIC_LABEL[metric]} の推移`,
    color: METRIC_COLOR[metric],
    delta: transformHistoryToDelta(points, metric),
  }));

  const chartData: Record<CompareMetric, HistoryPoint[]> =
    displayMode === "delta"
      ? {
          viewCount: presentations[0].delta.points,
          likeCount: presentations[1].delta.points,
          commentsCount: presentations[2].delta.points,
        }
      : { viewCount: points, likeCount: points, commentsCount: points };

  return (
    <>
      {displayMode === "delta" && (
        <DeltaModeNotice presentations={presentations} />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {presentations.map((p) => (
          <TimeSeriesChart
            key={p.metric}
            points={chartData[p.metric]}
            metric={p.metric}
            label={p.label}
            color={p.color}
          />
        ))}
      </div>
    </>
  );
}

function DeltaModeNotice({
  presentations,
}: {
  presentations: MetricPresentation[];
}) {
  return (
    <div
      role="note"
      className="notice-panel notice-panel--info px-4 py-3 text-xs sm:text-sm text-fg-primary flex flex-col gap-2"
    >
      <div>
        <span className="font-semibold text-accent-purple">増加数モード</span>
        <span className="ml-2 text-fg-secondary">
          選択期間内の「最初の実測値」を基準 (0) とし、以降の各測定点との差分を表示します。
          値が減少した場合は負の差分になります。
        </span>
      </div>
      <ul className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {presentations.map((p) => {
          const empty = p.delta.baselineFetchedAt === null;
          const only1 = !empty && p.delta.insufficient;
          return (
            <li
              key={p.metric}
              className="flex flex-col gap-0.5"
            >
              <div className="flex items-center gap-2">
                <span
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: p.color }}
                />
                <span className="text-xs font-medium text-fg-primary">
                  {METRIC_LABEL[p.metric]}
                </span>
              </div>
              {empty ? (
                <span className="text-[11px] text-neg">
                  期間内に実測値がありません
                </span>
              ) : only1 ? (
                <>
                  <span className="text-[11px] text-accent-yellow">
                    履歴が1件のみのため、増加傾向を判断できません
                  </span>
                  <span className="text-[11px] text-fg-muted tnum">
                    基準: {formatIsoToJst(p.delta.baselineFetchedAt as string)}
                    （{formatNumber(p.delta.baselineValue)}）
                  </span>
                </>
              ) : (
                <span className="text-[11px] text-fg-muted tnum">
                  基準: {formatIsoToJst(p.delta.baselineFetchedAt as string)}
                  （{formatNumber(p.delta.baselineValue)}）
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
