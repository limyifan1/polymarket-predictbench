export type Contract = {
  contract_id: string;
  market_id: string;
  name: string;
  outcome_type: string | null;
  current_price: number | null;
  confidence: number | null;
  implied_probability: number | null;
  raw_data?: Record<string, unknown> | null;
};

export type Market = {
  market_id: string;
  slug: string | null;
  question: string;
  category: string | null;
  sub_category: string | null;
  open_time: string | null;
  close_time: string | null;
  volume_usd: number | null;
  liquidity_usd: number | null;
  fee_bps: number | null;
  status: string;
  archived: boolean;
  last_synced_at: string;
  description: string | null;
  icon_url: string | null;
  contracts: Contract[];
};

export type MarketListResponse = {
  total: number;
  items: Market[];
};
