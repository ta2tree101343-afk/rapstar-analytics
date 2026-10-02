import type { AnalyticsClient } from "./client";
import type {
  CompareRequest,
  CompareResponse,
  HistoryResponse,
  PostDetail,
  RankingResponse,
  RankingType,
  StatusResponse,
} from "./types";

/**
 * Real Read API client. Talks to the SAM-deployed HTTP API endpoint.
 *
 * SECURITY:
 *   - No AWS credentials, tokens, or App secrets are read here. The backend
 *     is a public read-only API; the frontend never forwards secrets.
 *   - `credentials: "omit"` so cookies are never sent cross-origin.
 *   - The base URL comes from Vite build-time env `VITE_API_BASE_URL`.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function fetchJson<T>(baseUrl: string, path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(path, baseUrl);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") {
        url.searchParams.set(k, String(v));
      }
    }
  }
  let res: Response;
  try {
    res = await fetch(url.toString(), { credentials: "omit" });
  } catch (e) {
    throw new ApiError(0, "network_error", (e as Error).message || "network error");
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    // fall through with body = null
  }
  if (!res.ok) {
    const parsed = (body && typeof body === "object" ? body : {}) as { error?: string; message?: string };
    throw new ApiError(res.status, parsed.error || "http_error", parsed.message || `HTTP ${res.status}`);
  }
  return body as T;
}

export function createApiClient(baseUrl: string): AnalyticsClient {
  if (!baseUrl) throw new Error("createApiClient: baseUrl is required");
  const trimmedBase = baseUrl.replace(/\/+$/, "");
  return {
    async getStatus(): Promise<StatusResponse> {
      return fetchJson<StatusResponse>(trimmedBase, "/api/status");
    },
    async getRankings({ type }: { type: RankingType }): Promise<RankingResponse> {
      return fetchJson<RankingResponse>(trimmedBase, "/api/rankings", { type });
    },
    async getPost(postId: string): Promise<PostDetail> {
      return fetchJson<PostDetail>(trimmedBase, `/api/posts/${encodeURIComponent(postId)}`);
    },
    async getPostHistory(postId: string, range: "24h" | "7d" | "all"): Promise<HistoryResponse> {
      return fetchJson<HistoryResponse>(
        trimmedBase,
        `/api/posts/${encodeURIComponent(postId)}/history`,
        { range },
      );
    },
    async getCompareData(params: CompareRequest): Promise<CompareResponse> {
      const q: Record<string, string | number | undefined> = { range: params.range };
      if (params.scope) q.scope = params.scope;
      if (params.metric) q.metric = params.metric;
      if (params.ids && params.ids.length > 0) q.ids = params.ids.join(",");
      return fetchJson<CompareResponse>(trimmedBase, "/api/compare", q);
    },
  };
}
