import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { getClient } from "../api/client";
import { CompareChart } from "../components/CompareChart";
import { CompareStatusBar } from "../components/CompareStatusBar";
import { EmptyState, ErrorState } from "../components/EmptyState";
import {
  buildRechartsSeries,
  colorForPostId,
  computeCycleSnapshot,
  findCycleForTime,
  METRIC_LABEL,
  resolveCycles,
  transformSeriesToDelta,
  type CollectionCycle,
  type CompareMetric,
  type CycleSnapshotEntry,
} from "../lib/compare";
import { formatIsoToJst, formatNumber } from "../lib/formatters";
import type { RankingItem } from "../api/types";

type Range = "24h" | "7d" | "all";
type Preset = "top10" | "all" | "custom";
type DisplayMode = "cumulative" | "delta";

const DISPLAY_MODE_LABEL: Record<DisplayMode, string> = {
  cumulative: "累計値",
  delta: "増加数",
};

const RANGE_LABELS: Record<Range, string> = {
  "24h": "過去24時間",
  "7d": "過去7日",
  "all": "全期間",
};

const METRIC_TABS: CompareMetric[] = ["viewCount", "likeCount", "commentsCount"];
const TOP_N = 10;

export function ComparePage() {
  const [range, setRange] = useState<Range>("7d");
  const [metric, setMetric] = useState<CompareMetric>("viewCount");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("cumulative");
  const [query, setQuery] = useState("");
  const [customIds, setCustomIds] = useState<Set<string>>(new Set());
  const [preset, setPreset] = useState<Preset>("top10");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [highlighted, setHighlighted] = useState<Set<string>>(new Set());
  const [hoverT, setHoverT] = useState<number | null>(null);
  const [pinnedT, setPinnedT] = useState<number | null>(null);
  const selectedT = pinnedT ?? hoverT;

  const client = getClient();

  const rankingsQuery = useQuery({
    queryKey: ["rankings", "cumulative_views"],
    queryFn: () => client.getRankings({ type: "cumulative_views" }),
  });
  const allEntries: RankingItem[] = rankingsQuery.data?.items ?? [];

  // Sorted ids for `scope=custom` so query cache keys stay stable.
  const sortedCustomIds = Array.from(customIds).sort();

  const apiScope = preset === "custom" ? "selected" : preset;
  const compareQuery = useQuery({
    queryKey: ["compare", { range, scope: apiScope, metric, ids: sortedCustomIds }],
    queryFn: () =>
      client.getCompareData({
        range,
        scope: apiScope,
        metric,
        ids: preset === "custom" ? sortedCustomIds : undefined,
      }),
    // scope=selected with no ids returns 400 from the backend. Skip fetch
    // until the user picks at least one target.
    enabled: preset !== "custom" || customIds.size > 0,
  });

  const returnedSeries = compareQuery.data?.series ?? [];
  const returnedIds = new Set<string>(returnedSeries.map((s) => s.postId));

  const selectedIds: Set<string> = preset === "custom" ? customIds : returnedIds;

  const deltaSeries =
    displayMode === "cumulative"
      ? returnedSeries
      : returnedSeries.map((s) => transformSeriesToDelta(s, metric).series);

  const visibleSeries = buildRechartsSeries(
    deltaSeries.filter((s) => !hidden.has(s.postId)),
    metric,
  );

  // Collection cycles for the current view. Prefer the API's `runs` payload
  // (authoritative fetch-run intervals from DynamoDB); if it's not present
  // (older backend that hasn't been redeployed yet), fall back to clustering
  // the visible series' measurement timestamps. The fallback is a degrade
  // path — once the backend returns `runs`, that path takes over.
  const cycles = useMemo(
    () => resolveCycles(compareQuery.data?.runs, visibleSeries),
    [compareQuery.data?.runs, visibleSeries],
  );

  // The cycle for the current selection. All value reads (bottom list,
  // marker/guideline snap) go through this — so any two points in the same
  // cycle resolve to the same result regardless of which post was clicked.
  const selectedCycle: CollectionCycle | null =
    selectedT !== null && cycles.length > 0
      ? findCycleForTime(selectedT, cycles)
      : null;

  // Measurement-time envelope of what's currently plotted. Used to auto-clear
  // selections that fall outside the visible time range (after a mode/range
  // /preset/hidden toggle). This is intentionally NOT gated on `cycles` — we
  // must not clear the selection just because cycle info is unavailable, or
  // hover / click would stop rendering the guideline and per-series markers.
  const measurementRange = useMemo(() => {
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    for (const s of visibleSeries) {
      for (const p of s.data) {
        if (p.t < min) min = p.t;
        if (p.t > max) max = p.t;
      }
    }
    return Number.isFinite(min) ? { min, max } : null;
  }, [visibleSeries]);

  useEffect(() => {
    if (pinnedT == null) return;
    if (!measurementRange) {
      setPinnedT(null);
      return;
    }
    if (pinnedT < measurementRange.min || pinnedT > measurementRange.max) {
      setPinnedT(null);
    }
  }, [pinnedT, measurementRange]);
  useEffect(() => {
    if (hoverT == null) return;
    if (!measurementRange) {
      setHoverT(null);
      return;
    }
    if (hoverT < measurementRange.min || hoverT > measurementRange.max) {
      setHoverT(null);
    }
  }, [hoverT, measurementRange]);

  const cycleEntries: CycleSnapshotEntry[] =
    selectedCycle !== null && visibleSeries.length > 0
      ? computeCycleSnapshot(selectedCycle, visibleSeries)
      : [];

  const clearSelection = () => {
    setPinnedT(null);
    setHoverT(null);
  };

  const handleChartHover = (t: number | null) => {
    // Once pinned, hover no longer steers the panel. This is what makes
    // "tap on mobile → stays" work: after a click sets pinnedT, subsequent
    // stray onMouseMove events (from Recharts on touch) don't overwrite it.
    if (pinnedT != null) return;
    setHoverT(t);
  };
  const handleChartSelect = (t: number) => {
    setPinnedT(t);
  };

  const handleChartKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (cycles.length === 0) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const baseT = pinnedT ?? hoverT ?? cycles[cycles.length - 1].startedAt;
      const currentIdx = (() => {
        const c = findCycleForTime(baseT, cycles);
        if (c === null) return -1;
        return cycles.findIndex((cc) => cc.runId === c.runId);
      })();
      const nextIdx =
        e.key === "ArrowRight"
          ? Math.min(currentIdx + 1, cycles.length - 1)
          : Math.max(currentIdx - 1, 0);
      // Pin to the midpoint of the next cycle so subsequent findCycleForTime
      // lands squarely inside it (also plays nicely with Recharts snap).
      const nc = cycles[nextIdx];
      setPinnedT(Math.round((nc.startedAt + nc.finishedAt) / 2));
    } else if (e.key === "Escape") {
      clearSelection();
    }
  };

  const filteredForList = (() => {
    const q = query.trim().toLowerCase();
    return allEntries
      .slice()
      .sort((a, b) => (a.rapperName ?? "").localeCompare(b.rapperName ?? ""))
      .filter((e) => !q || (e.rapperName ?? "").toLowerCase().includes(q));
  })();

  const toggleChecked = (postId: string) => {
    const base = new Set<string>(preset === "custom" ? customIds : selectedIds);
    if (base.has(postId)) base.delete(postId);
    else base.add(postId);
    setCustomIds(base);
    if (preset !== "custom") setPreset("custom");
  };

  const toggleHidden = (postId: string) => {
    const next = new Set(hidden);
    if (next.has(postId)) next.delete(postId);
    else next.add(postId);
    setHidden(next);
  };

  const toggleHighlight = (postId: string) => {
    const next = new Set(highlighted);
    if (next.has(postId)) next.delete(postId);
    else next.add(postId);
    setHighlighted(next);
  };

  const clearHighlight = () => setHighlighted(new Set());

  const applyPreset = (p: "top10" | "all") => {
    setPreset(p);
    setCustomIds(new Set());
    setHidden(new Set());
  };

  return (
    <section className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold">全体比較</h1>
      </div>

      <div className="flex flex-wrap gap-2 items-center">
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
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap",
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
          role="tablist"
          aria-label="指標"
          className="inline-flex rounded-lg border border-border-strong bg-bg-card p-1"
        >
          {METRIC_TABS.map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={metric === m}
              onClick={() => setMetric(m)}
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap",
                metric === m
                  ? "bg-bg-base text-fg-primary"
                  : "text-fg-secondary hover:text-fg-primary",
              )}
            >
              {METRIC_LABEL[m]}
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
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap",
                range === r
                  ? "bg-bg-base text-fg-primary"
                  : "text-fg-secondary hover:text-fg-primary",
              )}
            >
              {RANGE_LABELS[r]}
            </button>
          ))}
        </div>

        <div
          role="radiogroup"
          aria-label="表示対象プリセット"
          className="inline-flex rounded-lg border border-border-strong bg-bg-card p-1"
        >
          {(
            [
              { id: "top10", label: `上位${TOP_N}人` },
              { id: "all", label: "全員" },
              { id: "custom", label: "カスタム" },
            ] as const
          ).map((opt) => (
            <button
              key={opt.id}
              role="radio"
              aria-checked={preset === opt.id}
              onClick={() =>
                opt.id === "custom"
                  ? (setPreset("custom"), setCustomIds(new Set(selectedIds)))
                  : applyPreset(opt.id)
              }
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap",
                preset === opt.id
                  ? "bg-bg-base text-fg-primary"
                  : "text-fg-secondary hover:text-fg-primary",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {highlighted.size > 0 && (
          <button
            onClick={clearHighlight}
            className="rounded-md border border-border-strong bg-bg-card px-3 py-1.5 text-sm font-medium text-accent-yellow hover:border-accent-yellow"
          >
            強調をクリア ({highlighted.size})
          </button>
        )}
      </div>

      {rankingsQuery.isError && (
        <ErrorState
          message="対象応募動画の一覧を取得できませんでした。"
          onRetry={() => rankingsQuery.refetch()}
        />
      )}
      {compareQuery.isPending && preset !== "custom" && (
        <div className="h-64 animate-pulse bg-bg-card/50" />
      )}
      {compareQuery.isError && (
        <ErrorState
          message="比較データの取得に失敗しました。"
          onRetry={() => compareQuery.refetch()}
        />
      )}
      {preset === "custom" && customIds.size === 0 && (
        <EmptyState
          title="カスタム選択: 対象が未選択です"
          hint="右のパネルで比較したい応募者にチェックを入れてください。"
        />
      )}

      {(rankingsQuery.data || compareQuery.data) && (
        <>
          <CompareStatusBar
            totalEntries={rankingsQuery.data?.totalEligible ?? 0}
            displayedCount={visibleSeries.length}
            truncated={compareQuery.data?.truncated}
            truncatedIncluded={compareQuery.data?.truncatedIncluded}
            truncatedOmitted={compareQuery.data?.truncatedOmitted}
            onSwitchToCustom={
              compareQuery.data?.truncated
                ? () => {
                    setPreset("custom");
                    setCustomIds(new Set(selectedIds));
                  }
                : undefined
            }
          />

          <div
            role="application"
            aria-label="時系列比較グラフ"
            tabIndex={0}
            onKeyDown={handleChartKeyDown}
            className="outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-fg-primary rounded-lg"
          >
            <CompareChart
              series={visibleSeries}
              yLabel={
                displayMode === "delta"
                  ? `${METRIC_LABEL[metric]} の増加数 (期間内の最初の実測値からの差分)`
                  : METRIC_LABEL[metric]
              }
              highlightedIds={highlighted}
              selectedT={selectedT}
              selectedCycle={selectedCycle}
              onHoverTime={handleChartHover}
              onSelectTime={handleChartSelect}
            />
          </div>

          <SelectionSnapshotPanel
            selectedCycle={selectedCycle}
            pinned={pinnedT !== null}
            entries={cycleEntries}
            metric={metric}
            displayMode={displayMode}
            onClear={clearSelection}
          />

          <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px] gap-6 md:gap-8 border-t border-border-subtle pt-4 md:h-96">
            <LegendPanel
              series={visibleSeries}
              highlighted={highlighted}
              hidden={hidden}
              onToggleHighlight={toggleHighlight}
              onToggleHidden={toggleHidden}
            />

            <SelectionPanel
              entries={filteredForList}
              selected={selectedIds}
              highlighted={highlighted}
              totalEntries={rankingsQuery.data?.totalEligible ?? 0}
              query={query}
              metric={metric}
              preset={preset}
              onQuery={setQuery}
              onToggleChecked={toggleChecked}
              onToggleHighlight={toggleHighlight}
            />
          </div>
        </>
      )}
    </section>
  );
}

function SelectionSnapshotPanel({
  selectedCycle,
  pinned,
  entries,
  metric,
  displayMode,
  onClear,
}: {
  selectedCycle: CollectionCycle | null;
  pinned: boolean;
  entries: CycleSnapshotEntry[];
  metric: CompareMetric;
  displayMode: DisplayMode;
  onClear: () => void;
}) {
  if (selectedCycle === null || entries.length === 0) {
    return (
      <p className="text-xs text-fg-muted">
        グラフをクリック / タップ、または PC ではホバーすると、その収集回に取得された各応募者の実測値をまとめて表示します。矢印キーで収集回単位に移動できます。
      </p>
    );
  }
  const startIso = new Date(selectedCycle.startedAt).toISOString();
  const inCycleCount = entries.filter((e) => e.inCycle).length;
  const missingCount = entries.length - inCycleCount;
  const metricLabel =
    displayMode === "delta" ? `${METRIC_LABEL[metric]} の増加数` : METRIC_LABEL[metric];
  return (
    <div
      role="region"
      aria-label="選択した収集回の各応募者スナップショット"
      className="border-t border-border-subtle pt-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0">
          <span className="text-xs uppercase tracking-wider text-fg-secondary">選択した収集回</span>
          <span className="tnum text-fg-primary font-semibold">
            {formatIsoToJst(startIso)}
          </span>
          {pinned && (
            <span className="text-[10px] font-medium text-fg-primary">
              ・固定中
            </span>
          )}
        </div>
        <button
          onClick={onClear}
          className="text-xs text-fg-muted hover:text-fg-primary min-h-[32px] px-2"
          aria-label="選択解除"
        >
          ✕
        </button>
      </div>
      {missingCount > 0 && (
        <div className="mt-1 text-[11px] text-accent-yellow">
          {missingCount} 名は本収集回に実測データがありません。
        </div>
      )}
      <ul
        className="mt-2 max-h-72 overflow-y-auto overscroll-contain divide-y divide-border-subtle"
        aria-label={`${metricLabel} の一覧 (${inCycleCount}/${entries.length} 名)`}
      >
        {entries.map((e) => {
          return (
            <li key={e.postId} className="flex items-center gap-3 py-2 text-sm">
              <span
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{
                  backgroundColor: e.color,
                  opacity: e.inCycle ? 1 : 0.35,
                }}
              />
              <Link
                to={`/posts/${encodeURIComponent(e.postId)}`}
                className={clsx(
                  "min-w-0 flex-1 truncate hover:text-accent-yellow",
                  e.inCycle ? "text-fg-primary" : "text-fg-muted",
                )}
              >
                {e.rapperName ?? e.postId}
              </Link>
              <div className="flex flex-col items-end shrink-0">
                <span
                  className={clsx(
                    "tnum font-semibold",
                    e.inCycle ? "text-fg-primary" : "text-fg-muted",
                  )}
                >
                  {e.value === null ? "データなし" : formatNumber(e.value)}
                </span>
                <span className="text-[10px] text-fg-muted tnum">
                  {e.inCycle
                    ? e.actualFetchedAt
                      ? formatIsoToJst(e.actualFetchedAt)
                      : "—"
                    : "この収集回のデータなし"}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function LegendPanel({
  series,
  highlighted,
  hidden,
  onToggleHighlight,
  onToggleHidden,
}: {
  series: Array<{ postId: string; rapperName: string | null; color: string }>;
  highlighted: Set<string>;
  hidden: Set<string>;
  onToggleHighlight: (postId: string) => void;
  onToggleHidden: (postId: string) => void;
}) {
  if (series.length === 0) {
    return (
      <EmptyState
        title="表示中の系列がありません"
        hint="右のパネルから応募者を選択してください。"
      />
    );
  }
  return (
    <div className="md:flex md:flex-col md:h-full md:min-h-0">
      <div className="mb-2 text-xs font-medium uppercase tracking-wider text-fg-secondary">
        表示中の系列 (凡例)
      </div>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 max-h-72 md:max-h-none md:flex-1 md:min-h-0 overflow-y-auto">
        {series.map((s) => {
          const isHi = highlighted.has(s.postId);
          const isHidden = hidden.has(s.postId);
          return (
            <li
              key={s.postId}
              className={clsx(
                "flex items-center gap-2 rounded px-2 py-1.5 transition-colors",
                isHi ? "row-highlighted" : "hover:bg-bg-elevated",
                isHidden && "opacity-40",
              )}
            >
              <button
                onClick={() => onToggleHighlight(s.postId)}
                aria-pressed={isHi}
                aria-label={`${s.rapperName ?? s.postId} を強調表示 (${isHi ? "解除" : "有効化"})`}
                className="flex items-center gap-2 flex-1 min-w-0 text-left"
              >
                <span
                  className="inline-block h-3 w-3 shrink-0 rounded-sm"
                  style={{ backgroundColor: s.color }}
                />
                <span
                  className={clsx(
                    "min-w-0 truncate text-sm",
                    isHi ? "font-semibold text-fg-primary" : "text-fg-primary",
                  )}
                >
                  {s.rapperName ?? s.postId}
                </span>
              </button>
              <button
                onClick={() => onToggleHidden(s.postId)}
                className="shrink-0 rounded p-1 text-fg-secondary hover:text-fg-primary hover:bg-bg-elevated"
                aria-label={`${s.rapperName ?? s.postId} の表示を${isHidden ? "有効" : "無効"}にする`}
                aria-pressed={!isHidden}
                title={isHidden ? "表示する" : "非表示にする"}
              >
                {isHidden ? "◌" : "●"}
              </button>
              <Link
                to={`/posts/${encodeURIComponent(s.postId)}`}
                className="shrink-0 text-[11px] text-accent-yellow hover:underline"
              >
                詳細
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SelectionPanel({
  entries,
  selected,
  highlighted,
  totalEntries,
  query,
  metric,
  preset,
  onQuery,
  onToggleChecked,
  onToggleHighlight,
}: {
  entries: RankingItem[];
  selected: Set<string>;
  highlighted: Set<string>;
  totalEntries: number;
  query: string;
  metric: CompareMetric;
  preset: Preset;
  onQuery: (v: string) => void;
  onToggleChecked: (postId: string) => void;
  onToggleHighlight: (postId: string) => void;
}) {
  return (
    <div className="md:flex md:flex-col md:h-full md:min-h-0">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs font-medium uppercase tracking-wider text-fg-secondary">
          比較対象を選択
        </div>
        <div className="text-[11px] text-fg-muted tnum">
          選択 {selected.size} / 全 {totalEntries}
        </div>
      </div>
      <input
        type="search"
        inputMode="search"
        placeholder="ラッパー名で検索"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        className="mb-2 w-full rounded-md border border-border-strong bg-transparent px-3 py-2 text-sm text-fg-primary placeholder:text-fg-muted focus:border-accent-yellow"
      />
      <div className="max-h-72 md:max-h-none md:flex-1 md:min-h-0 overflow-y-auto">
        <ul className="divide-y divide-border-subtle">
          {entries.map((e) => {
            const isSelected = selected.has(e.postId);
            const isHi = highlighted.has(e.postId);
            const latest = e.cumulative[metric];
            return (
              <li
                key={e.postId}
                className={clsx(
                  "flex items-center gap-2 px-2 py-1.5 transition-colors",
                  isHi ? "row-highlighted" : "hover:bg-bg-elevated",
                )}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => onToggleChecked(e.postId)}
                  aria-label={`${e.rapperName ?? e.postId} を比較対象に${isSelected ? "含める" : "追加する"}`}
                  className="accent-accent-yellow shrink-0"
                />
                <span
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: colorForPostId(e.postId) }}
                />
                <button
                  onClick={() => onToggleHighlight(e.postId)}
                  aria-pressed={isHi}
                  aria-label={`${e.rapperName ?? e.postId} を強調表示 (${isHi ? "解除" : "有効化"})`}
                  className={clsx(
                    "min-w-0 flex-1 text-left truncate text-sm",
                    isHi ? "font-semibold text-fg-primary" : "text-fg-primary",
                  )}
                >
                  {e.rapperName ?? "(名前未取得)"}
                </button>
                <span
                  className="tnum text-[11px] text-fg-muted shrink-0"
                  title={`最新 ${METRIC_LABEL[metric]}`}
                >
                  {latest === null || latest === undefined ? "—" : formatNumber(latest)}
                </span>
              </li>
            );
          })}
          {entries.length === 0 && (
            <li className="px-2 py-3 text-center text-xs text-fg-muted">
              該当する応募者がありません
            </li>
          )}
        </ul>
      </div>
      {preset !== "custom" && (
        <div className="mt-2 text-[11px] text-fg-muted">
          チェックを変更するとカスタム選択に切り替わります。
        </div>
      )}
    </div>
  );
}
