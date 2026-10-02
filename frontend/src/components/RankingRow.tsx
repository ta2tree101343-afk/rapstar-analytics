import { Link } from "react-router-dom";
import type { RankingItem, RankingType } from "../api/types";
import { formatIsoToJst, formatNumber, formatSignedNumber } from "../lib/formatters";
import { clsx } from "clsx";

interface Props {
  item: RankingItem & { rank: number | null };
  type: RankingType;
}

function reasonLabel(reason: RankingItem["reason"]): string {
  switch (reason) {
    case "insufficient_data":
      return "データ不足";
    case "too_new":
      return "投稿から24h未満";
    case "no_metric":
      return "取得不可";
    default:
      return "—";
  }
}

export function RankingRow({ item, type }: Props) {
  const isDelta = type.startsWith("delta_");
  const valueColor = isDelta && item.value !== null
    ? item.value > 0
      ? "text-pos"
      : item.value < 0
        ? "text-neg"
        : "text-fg-primary"
    : "text-fg-primary";

  return (
    <article
      className="group px-1 py-3 sm:px-2 sm:py-3.5 transition-colors hover:bg-bg-card/60"
    >
      <div className="flex items-start gap-3 sm:gap-4">
        <div className="shrink-0 w-10 sm:w-12 text-center">
          <div
            className={clsx(
              "tnum font-bold tracking-tight",
              item.rank === null
                ? "text-fg-muted text-sm"
                : item.rank === 1
                  ? "text-2xl sm:text-3xl text-accent-yellow"
                  : item.rank <= 3
                    ? "text-xl sm:text-2xl text-accent-yellow/85"
                    : "text-lg sm:text-xl text-fg-secondary",
            )}
          >
            {item.rank === null ? "—" : `${item.rank}`}
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <Link
              to={`/posts/${encodeURIComponent(item.postId)}`}
              className="text-base sm:text-lg font-semibold text-fg-primary hover:text-accent-yellow transition-colors truncate"
            >
              {item.rapperName ?? "(名前未取得)"}
            </Link>
            <div className={clsx("tnum text-lg sm:text-2xl font-bold tracking-tight", valueColor)}>
              {isDelta ? formatSignedNumber(item.value) : formatNumber(item.value)}
              {item.value === null && (
                <span className="ml-2 text-xs font-normal text-fg-muted">
                  {reasonLabel(item.reason)}
                </span>
              )}
            </div>
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-secondary">
            <span>
              投稿: <span className="tnum">{formatIsoToJst(item.postedAt)}</span>
            </span>
            <span>
              取得: <span className="tnum">{formatIsoToJst(item.latestFetchedAt)}</span>
            </span>
            {isDelta && item.delta && (
              <span title={`実比較時刻: ${item.delta.referenceFetchedAt}`}>
                比較期間: 約 <span className="tnum">{item.delta.actualHoursBetween.toFixed(1)}</span> 時間
              </span>
            )}
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-fg-muted">
            <span>再生: <span className="tnum text-fg-secondary">{formatNumber(item.cumulative.viewCount)}</span></span>
            <span>いいね: <span className="tnum text-fg-secondary">{formatNumber(item.cumulative.likeCount)}</span></span>
            <span>コメント: <span className="tnum text-fg-secondary">{formatNumber(item.cumulative.commentsCount)}</span></span>
            <a
              href={item.permalink}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto text-accent-yellow hover:underline"
            >
              Instagram で見る ↗
            </a>
          </div>
        </div>
      </div>
    </article>
  );
}
