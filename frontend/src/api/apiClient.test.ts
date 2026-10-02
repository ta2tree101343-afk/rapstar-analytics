import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { createApiClient, ApiError } from "./apiClient";

const BASE = "https://api.example.test";

describe("apiClient", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function jsonResp(body: unknown, status = 200) {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("getStatus GETs /api/status with no auth headers", async () => {
    fetchMock.mockResolvedValue(jsonResp({ entryCount: 133, isMock: false }));
    const c = createApiClient(BASE);
    const s = await c.getStatus();
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(`${BASE}/api/status`);
    expect((init as RequestInit).credentials).toBe("omit");
    expect(s.entryCount).toBe(133);
  });

  it("getRankings passes the ranking type as query string", async () => {
    fetchMock.mockResolvedValue(jsonResp({ items: [], totalEligible: 0 }));
    await createApiClient(BASE).getRankings({ type: "delta_views_24h" });
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      `${BASE}/api/rankings?type=delta_views_24h`,
    );
  });

  it("getPost URL-encodes the postId", async () => {
    fetchMock.mockResolvedValue(jsonResp({ postId: "P/1" }));
    await createApiClient(BASE).getPost("P/1");
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}/api/posts/P%2F1`);
  });

  it("getPostHistory includes range", async () => {
    fetchMock.mockResolvedValue(jsonResp({ points: [] }));
    await createApiClient(BASE).getPostHistory("A", "7d");
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      `${BASE}/api/posts/A/history?range=7d`,
    );
  });

  it("getCompareData serializes scope, metric, and ids", async () => {
    fetchMock.mockResolvedValue(jsonResp({ series: [] }));
    await createApiClient(BASE).getCompareData({
      range: "7d",
      scope: "selected",
      metric: "viewCount",
      ids: ["A", "B", "C"],
    });
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      `${BASE}/api/compare?range=7d&scope=selected&metric=viewCount&ids=A%2CB%2CC`,
    );
  });

  it("getCompareData omits ids when empty", async () => {
    fetchMock.mockResolvedValue(jsonResp({ series: [] }));
    await createApiClient(BASE).getCompareData({
      range: "24h",
      scope: "top10",
      metric: "likeCount",
      ids: [],
    });
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).not.toMatch(/[?&]ids=/);
    expect(url).toContain("scope=top10");
    expect(url).toContain("metric=likeCount");
  });

  it("throws ApiError with parsed backend code on 4xx", async () => {
    fetchMock.mockResolvedValue(
      jsonResp({ error: "invalid_type", message: "unknown ranking type" }, 400),
    );
    const p = createApiClient(BASE).getRankings({ type: "cumulative_views" });
    await expect(p).rejects.toBeInstanceOf(ApiError);
    await p.catch((e: ApiError) => {
      expect(e.status).toBe(400);
      expect(e.code).toBe("invalid_type");
    });
  });

  it("returns a network_error ApiError when fetch throws", async () => {
    fetchMock.mockRejectedValue(new Error("boom"));
    const p = createApiClient(BASE).getStatus();
    await expect(p).rejects.toBeInstanceOf(ApiError);
    await p.catch((e: ApiError) => {
      expect(e.status).toBe(0);
      expect(e.code).toBe("network_error");
    });
  });

  it("trims trailing slash from base URL", async () => {
    fetchMock.mockResolvedValue(jsonResp({}));
    await createApiClient(`${BASE}/`).getStatus();
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}/api/status`);
  });
});
