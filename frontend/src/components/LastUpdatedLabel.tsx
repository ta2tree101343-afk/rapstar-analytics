import { formatIsoToJst } from "../lib/formatters";

export function LastUpdatedLabel({ iso }: { iso: string | null | undefined }) {
  return (
    <span className="text-[11px] sm:text-xs text-fg-muted">
      最終取得: <span className="tnum text-fg-secondary">{formatIsoToJst(iso)}</span> JST
    </span>
  );
}
