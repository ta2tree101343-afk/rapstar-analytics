import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HistoryPoint } from "../api/types";
import { formatIsoToJst, formatNumber } from "../lib/formatters";

type Metric = "viewCount" | "likeCount" | "commentsCount";

interface Props {
  points: HistoryPoint[];
  metric: Metric;
  label: string;
  color: string;
}

/**
 * Line chart of a single metric over time. Uses `connectNulls={false}` so
 * missing observations render as gaps — NEVER interpolate.
 */
export function TimeSeriesChart({ points, metric, label, color }: Props) {
  const data = points.map((p) => ({
    t: new Date(p.fetchedAt).getTime(),
    v: p[metric],
    fetchedAt: p.fetchedAt,
  }));

  if (data.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center text-sm text-fg-muted">
        {label}: 期間内の取得データがありません
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 text-xs font-medium uppercase tracking-wider text-fg-secondary">
        {label}
      </div>
      <div className="h-[220px] lg:h-[clamp(220px,calc(100dvh-540px),420px)]">
        <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2A2A34" />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t: number) =>
              new Intl.DateTimeFormat("ja-JP", {
                month: "2-digit",
                day: "2-digit",
                timeZone: "Asia/Tokyo",
              }).format(new Date(t))
            }
            stroke="#666673"
            tick={{ fill: "#9A9AA5", fontSize: 11 }}
          />
          <YAxis
            stroke="#666673"
            tick={{ fill: "#9A9AA5", fontSize: 11 }}
            tickFormatter={(v: number) => formatNumber(v)}
            width={64}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1B1B23",
              border: "1px solid #3B3B47",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelStyle={{ color: "#9A9AA5" }}
            itemStyle={{ color: "#E9E9EE" }}
            labelFormatter={(_v, payload) => {
              const p = payload && payload[0];
              return p ? formatIsoToJst((p.payload as { fetchedAt: string }).fetchedAt) : "";
            }}
            formatter={(v: unknown) => (v == null ? "—" : formatNumber(v as number))}
          />
          <Line
            type="linear"
            dataKey="v"
            name={label}
            stroke={color}
            strokeWidth={2}
            dot={{ r: 3, stroke: color, fill: "#0B0B0F" }}
            activeDot={{ r: 5 }}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
