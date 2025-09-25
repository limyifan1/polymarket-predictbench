import type { EventListResponse, MarketListResponse } from "@/types/market";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type MarketFilters = {
  status?: string;
  close_after?: string | null;
  close_before?: string | null;
  min_volume?: number | null;
  sort?: "close_time" | "volume_usd" | "liquidity_usd" | "last_synced_at";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
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

  return {
    status: get("status") ?? "open",
    close_after: toISOStringOrNull(closeAfterRaw, DATE_START_SUFFIX),
    close_before: toISOStringOrNull(closeBeforeRaw, DATE_END_SUFFIX),
    min_volume: get("min_volume") ? Number.parseFloat(get("min_volume")!) : null,
    sort: (get("sort") as MarketFilters["sort"]) ?? "close_time",
    order: (get("order") as MarketFilters["order"]) ?? "asc",
    limit: get("limit") ? Number.parseInt(get("limit")!, 10) : 50,
    offset: get("offset") ? Number.parseInt(get("offset")!, 10) : 0,
  };
}

function buildQuery(filters: MarketFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.close_after) params.set("close_after", filters.close_after);
  if (filters.close_before) params.set("close_before", filters.close_before);
  if (typeof filters.min_volume === "number" && !Number.isNaN(filters.min_volume)) {
    params.set("min_volume", filters.min_volume.toString());
  }
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.order) params.set("order", filters.order);
  if (typeof filters.limit === "number") params.set("limit", filters.limit.toString());
  if (typeof filters.offset === "number") params.set("offset", filters.offset.toString());
  return params.toString();
}

export async function fetchMarkets(filters: MarketFilters): Promise<MarketListResponse> {
  const query = buildQuery(filters);
  const response = await fetch(`${API_BASE_URL}/markets?${query}`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Failed to load markets: ${response.status}`);
  }

  return response.json() as Promise<MarketListResponse>;
}

export async function fetchEvents(filters: MarketFilters): Promise<EventListResponse> {
  const query = buildQuery(filters);
  const response = await fetch(`${API_BASE_URL}/events?${query}`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Failed to load events: ${response.status}`);
  }

  return response.json() as Promise<EventListResponse>;
}
