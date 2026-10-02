export type RankingType =
  | "cumulative_views"
  | "cumulative_likes"
  | "cumulative_comments"
  | "delta_views_24h"
  | "delta_likes_24h";

export interface StatusResponse {
  lastSuccessAt: string | null;
  lastSuccessStatus: string | null;
  entryCount: number;
  updatedAt: string;
  isMock: boolean;
}

export interface RankingItem {
  postId: string;
  rapperName: string | null;
  permalink: string;
  postedAt: string;
  latestFetchedAt: string | null;
  value: number | null;
  valueLabel: string;
  cumulative: {
    viewCount: number | null;
    likeCount: number | null;
    commentsCount: number | null;
  };
  delta?: {
    referenceFetchedAt: string;
    actualHoursBetween: number;
  } | null;
  reason?: "insufficient_data" | "too_new" | "no_metric" | null;
}

export interface RankingResponse {
  type: RankingType;
  items: RankingItem[];
  totalEligible: number;
  totalWithData: number;
  totalWithoutData: number;
  /**
   * Opaque cursor for the next page. Present only when the backend paginates
   * server-side (STEP 5-B onwards). Mock client omits this field.
   */
  nextCursor?: string | null;
  isMock: boolean;
}

export interface PostDetail {
  postId: string;
  rapperName: string | null;
  permalink: string;
  postedAt: string;
  caption: string | null;
  classification: "entry" | "unclassified" | "excluded";
  latest: {
    viewCount: number | null;
    likeCount: number | null;
    commentsCount: number | null;
    fetchedAt: string | null;
  };
  isMock: boolean;
}

export interface HistoryPoint {
  fetchedAt: string;
  viewCount: number | null;
  likeCount: number | null;
  commentsCount: number | null;
}

export interface HistoryResponse {
  postId: string;
  range: "24h" | "7d" | "all";
  points: HistoryPoint[];
  isMock: boolean;
}

export interface CompareSeries {
  postId: string;
  rapperName: string | null;
  permalink: string;
  postedAt: string;
  points: HistoryPoint[];
}

export type CompareScope = "all" | "top10" | "selected";
export type CompareMetric = "viewCount" | "likeCount" | "commentsCount";
export type CompareRange = "24h" | "7d" | "all";

export interface CompareRequest {
  range: CompareRange;
  scope?: CompareScope;
  ids?: string[];
  metric?: CompareMetric;
}

export interface FetchRunInfo {
  runId: string;
  startedAt: string;
  finishedAt: string;
  status: string | null;
  snapshotsWritten: number | null;
}

export interface CompareResponse {
  range: CompareRange;
  series: CompareSeries[];
  totalEntries: number;
  /**
   * Data-bearing collection runs (status success/partial with
   * snapshots_written > 0) that overlap the queried range. Each snapshot in
   * `series[i].points` was written by exactly one of these runs; the
   * frontend uses the intervals to group per-cycle for the "point selected"
   * panel. Missing/empty means "no cycle data" — the panel falls back to
   * showing the raw as-of value.
   */
  runs?: FetchRunInfo[];
  /**
   * Set to true by the backend when the response was capped by the total
   * data-point budget. `series` then contains only the highest-priority
   * entries (by latest metric); the omitted count is reported so the UI can
   * prompt the user to narrow via scope=selected.
   */
  truncated?: boolean;
  truncatedReason?: "response_too_large" | string;
  truncatedIncluded?: number;
  truncatedOmitted?: number;
  isMock: boolean;
}
