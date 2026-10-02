interface Props {
  totalEntries: number;
  displayedCount: number;
  truncated?: boolean;
  truncatedIncluded?: number;
  truncatedOmitted?: number;
  onSwitchToCustom?: () => void;
}

export function CompareStatusBar({
  totalEntries,
  displayedCount,
  truncated,
  truncatedIncluded,
  truncatedOmitted,
  onSwitchToCustom,
}: Props) {
  if (!truncated) return null;
  return (
    <div
      role="alert"
      className="notice-panel notice-panel--warning px-3 py-2 text-xs sm:text-sm text-fg-primary"
    >
      <div className="font-semibold text-accent-yellow">
        表示件数が制限されました
      </div>
      <div className="mt-1 text-fg-secondary">
        全 {totalEntries} 件のうち{" "}
        <span className="tnum text-fg-primary font-semibold">
          {truncatedIncluded ?? displayedCount}
        </span>{" "}
        件を表示中です（
        <span className="tnum text-fg-primary font-semibold">
          {truncatedOmitted ?? 0}
        </span>{" "}
        件を省略）。データ量が大きいため、対象を絞ってご覧ください。
      </div>
      {onSwitchToCustom && (
        <button
          onClick={onSwitchToCustom}
          className="mt-2 rounded border border-border-strong bg-bg-card px-3 py-1.5 text-xs font-medium text-fg-primary hover:border-fg-secondary transition-colors"
        >
          カスタムで対象を絞り込む
        </button>
      )}
    </div>
  );
}
