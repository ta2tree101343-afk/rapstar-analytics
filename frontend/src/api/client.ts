import type {
  CompareRequest,
  CompareResponse,
  HistoryResponse,
  PostDetail,
  RankingResponse,
  RankingType,
  StatusResponse,
} from "./types";
import { createMockClient } from "../mocks/mockClient";
import { createApiClient } from "./apiClient";

export interface AnalyticsClient {
  getStatus(): Promise<StatusResponse>;
  getRankings(params: { type: RankingType }): Promise<RankingResponse>;
  getPost(postId: string): Promise<PostDetail>;
  getPostHistory(postId: string, range: "24h" | "7d" | "all"): Promise<HistoryResponse>;
  getCompareData(params: CompareRequest): Promise<CompareResponse>;
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) || "";
const USE_MOCK =
  import.meta.env.VITE_USE_MOCK === "true" || !API_BASE_URL;

let cached: AnalyticsClient | null = null;

export function getClient(): AnalyticsClient {
  if (cached) return cached;
  cached = USE_MOCK ? createMockClient() : createApiClient(API_BASE_URL);
  return cached;
}

export const IS_MOCK = USE_MOCK;
