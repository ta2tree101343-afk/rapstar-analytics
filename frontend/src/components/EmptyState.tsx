export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="py-10 text-center">
      <div className="text-base font-medium text-fg-secondary">{title}</div>
      {hint && <div className="mt-2 text-sm text-fg-muted">{hint}</div>}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="notice-panel notice-panel--error p-6 text-center"
    >
      <div className="text-base font-medium text-neg">読み込みエラー</div>
      <div className="mt-1 text-sm text-fg-secondary">{message}</div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded-md border border-border-strong bg-bg-elevated px-4 py-2 text-sm font-medium text-fg-primary hover:border-fg-secondary"
        >
          再試行
        </button>
      )}
    </div>
  );
}

export function SkeletonRankingList() {
  return (
    <div className="divide-y divide-border-subtle">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-24 animate-pulse bg-bg-elevated/40" />
      ))}
    </div>
  );
}
