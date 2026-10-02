const NF = new Intl.NumberFormat("ja-JP");

export function formatNumber(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return NF.format(v);
}

export function formatSignedNumber(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const s = NF.format(Math.abs(v));
  if (v > 0) return `+${s}`;
  if (v < 0) return `−${s}`;
  return "0";
}

export function formatIsoToJst(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    const fmt = new Intl.DateTimeFormat("ja-JP", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Tokyo",
    });
    return fmt.format(d);
  } catch {
    return "—";
  }
}

export function formatIsoToRelativeJst(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (isNaN(then)) return "—";
  const now = Date.now();
  const diffMin = Math.round((now - then) / 60000);
  if (diffMin < 1) return "たった今";
  if (diffMin < 60) return `${diffMin}分前`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}時間前`;
  const diffD = Math.round(diffH / 24);
  if (diffD < 30) return `${diffD}日前`;
  return formatIsoToJst(iso);
}

export function hoursBetween(iso1: string, iso2: string): number {
  return Math.abs(new Date(iso1).getTime() - new Date(iso2).getTime()) / 3_600_000;
}
