export function MockDataBanner() {
  return (
    <div
      className="w-full bg-bg-elevated border-b border-border-subtle text-fg-primary"
      role="status"
      aria-live="polite"
    >
      <div className="mx-auto max-w-6xl px-4 py-2 text-xs sm:text-sm text-center">
        <span className="font-semibold text-accent-purple">MOCK DATA</span>
        <span className="mx-2 text-fg-secondary">|</span>
        <span className="text-fg-secondary">
          この画面はサンプルデータで動作しています。ラッパー名・数値・時刻はすべて架空です。
        </span>
      </div>
    </div>
  );
}
