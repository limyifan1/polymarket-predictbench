import type { DatasetOverview, EventListResponse, MarketListResponse } from "@/types/market";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const PROD_API_BASE_URL =
  process.env.NEXT_PUBLIC_PROD_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? API_BASE_URL;

export type MarketFilters = {
  status?: string;
  close_after?: string | null;
  close_before?: string | null;
  min_volume?: number | null;
  sort?: "close_time" | "volume_usd" | "liquidity_usd" | "last_synced_at";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
  dataset?: "local" | "production";
};

const DATE_END_SUFFIX = "T23:59:59Z";
const DATE_START_SUFFIX = "T00:00:00Z";

function toISOStringOrNull(value: string | undefined | null, suffix: string): string | null {
  if (!value) {
    return null;
  }

  try {
    const iso = new Date(value).toISOString();
    return iso;
  } catch (error) {
    return `${value}${suffix}`;
  }
}

export function parseFilters(searchParams: Record<string, string | string[] | undefined>): MarketFilters {
  const get = (key: string): string | undefined => {
    const value = searchParams[key];
    if (Array.isArray(value)) {
      return value.at(-1);
    }
    return value;
  };

  const closeAfterRaw = get("close_after");
  const closeBeforeRaw = get("close_before");
  const datasetRaw = (get("dataset") ?? "local").toLowerCase();
  const dataset: MarketFilters["dataset"] =
    datasetRaw === "production" || datasetRaw === "prod" ? "production" : "local";

  return {
    status: get("status") ?? "open",
    close_after: toISOStringOrNull(closeAfterRaw, DATE_START_SUFFIX),
    close_before: toISOStringOrNull(closeBeforeRaw, DATE_END_SUFFIX),
    min_volume: get("min_volume") ? Number.parseFloat(get("min_volume")!) : null,
    sort: (get("sort") as MarketFilters["sort"]) ?? "close_time",
    order: (get("order") as MarketFilters["order"]) ?? "asc",
    limit: get("limit") ? Number.parseInt(get("limit")!, 10) : 50,
    offset: get("offset") ? Number.parseInt(get("offset")!, 10) : 0,
    dataset,
  };
}

function buildQuery(filters: MarketFilters): string {
  const { dataset: _dataset, ...rest } = filters;
  const params = new URLSearchParams();
  if (rest.status) params.set("status", rest.status);
  if (rest.close_after) params.set("close_after", rest.close_after);
  if (rest.close_before) params.set("close_before", rest.close_before);
  if (typeof rest.min_volume === "number" && !Number.isNaN(rest.min_volume)) {
    params.set("min_volume", rest.min_volume.toString());
  }
  if (rest.sort) params.set("sort", rest.sort);
  if (rest.order) params.set("order", rest.order);
  if (typeof rest.limit === "number") params.set("limit", rest.limit.toString());
  if (typeof rest.offset === "number") params.set("offset", rest.offset.toString());
  return params.toString();
}

function resolveApiBase(dataset: MarketFilters["dataset"]): string {
  if (dataset === "production") {
    return PROD_API_BASE_URL;
  }
  return API_BASE_URL;
}

export async function fetchMarkets(filters: MarketFilters): Promise<MarketListResponse> {
  const query = buildQuery(filters);
  const baseUrl = resolveApiBase(filters.dataset);
  const response = await fetch(`${baseUrl}/markets?${query}`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Failed to load markets: ${response.status}`);
  }

  return response.json() as Promise<MarketListResponse>;
}

export async function fetchEvents(filters: MarketFilters): Promise<EventListResponse> {
  const query = buildQuery(filters);
  const baseUrl = resolveApiBase(filters.dataset);
  const url = `${baseUrl}/events?${query}`;
  const response = await fetch(url, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Failed to load events: ${response.status}`);
  }

  return response.json() as Promise<EventListResponse>;
}

export async function fetchDatasetOverview(
  dataset: MarketFilters["dataset"] = "local",
): Promise<DatasetOverview> {
  const baseUrl = resolveApiBase(dataset);
  const response = await fetch(`${baseUrl}/overview`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Failed to load dataset overview: ${response.status}`);
  }

  return response.json() as Promise<DatasetOverview>;
}
