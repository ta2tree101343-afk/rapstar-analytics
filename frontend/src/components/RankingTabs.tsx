import { clsx } from "clsx";
import type { RankingType } from "../api/types";

const TABS: Array<{ id: RankingType; label: string; short: string; group: "cumulative" | "delta" }> = [
  { id: "cumulative_views", label: "累計 再生数", short: "再生数", group: "cumulative" },
  { id: "cumulative_likes", label: "累計 いいね", short: "いいね", group: "cumulative" },
  { id: "cumulative_comments", label: "累計 コメント", short: "コメント", group: "cumulative" },
  { id: "delta_views_24h", label: "24h増 再生数", short: "24h 再生", group: "delta" },
  { id: "delta_likes_24h", label: "24h増 いいね", short: "24h いいね", group: "delta" },
];

interface Props {
  value: RankingType;
  onChange: (t: RankingType) => void;
}

export function RankingTabs({ value, onChange }: Props) {
  return (
    <div role="tablist" aria-label="ランキング種別" className="flex overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0">
      <div className="flex gap-1.5 sm:gap-2 min-w-max sm:min-w-0 sm:flex-wrap">
        {TABS.map((t) => {
          const active = value === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(t.id)}
              className={clsx(
                "shrink-0 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap",
                active
                  ? "border-accent-yellow bg-accent-yellow text-bg-base"
                  : "border-border-strong bg-bg-card text-fg-secondary hover:text-fg-primary hover:border-fg-secondary",
              )}
            >
              <span className="sm:hidden">{t.short}</span>
              <span className="hidden sm:inline">{t.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
