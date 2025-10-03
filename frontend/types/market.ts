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

export type ExperimentDescriptor = {
  experiment_name: string;
  experiment_version: string;
  variant_name: string;
  variant_version: string;
  stage: string;
};

export type ExperimentRunSummary = {
  run_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
};

export type PipelineRunSummary = {
  run_id: string;
  run_date: string;
  target_date: string;
  window_days: number;
  status: string;
  environment: string | null;
};

export type ResearchArtifact = {
  descriptor: ExperimentDescriptor;
  run: ExperimentRunSummary;
  pipeline_run: PipelineRunSummary | null;
  artifact_id: string | null;
  artifact_uri: string | null;
  artifact_hash: string | null;
  created_at: string;
  updated_at: string;
  payload: Record<string, unknown> | null;
};

export type ForecastResult = {
  descriptor: ExperimentDescriptor;
  run: ExperimentRunSummary;
  pipeline_run: PipelineRunSummary | null;
  recorded_at: string;
  score: number | null;
  artifact_uri: string | null;
  source_artifact_id: string | null;
  payload: Record<string, unknown> | null;
};

export type Event = {
  event_id: string;
  slug: string | null;
  title: string | null;
  description: string | null;
  start_time: string | null;
  end_time: string | null;
  icon_url: string | null;
  series_slug: string | null;
  series_title: string | null;
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
  event: Event | null;
  experiment_results: ForecastResult[];
};

export type MarketListResponse = {
  total: number;
  items: Market[];
};

export type EventWithMarkets = Event & {
  markets: Market[];
  market_count: number;
  research: ResearchArtifact[];
};

export type EventListResponse = {
  total: number;
  items: EventWithMarkets[];
};

export type MarketStatusCount = {
  status: string;
  count: number;
};

export type ExperimentVariantSummary = {
  stage: string;
  experiment_name: string;
  experiment_version: string;
  variant_name: string;
  variant_version: string;
  output_count: number;
  last_activity: string | null;
};

export type DatasetOverview = {
  generated_at: string;
  total_events: number;
  events_with_research: number;
  events_with_forecasts: number;
  total_markets: number;
  markets_with_forecasts: number;
  market_status: MarketStatusCount[];
  total_research_artifacts: number;
  total_forecast_results: number;
  research_variants: ExperimentVariantSummary[];
  forecast_variants: ExperimentVariantSummary[];
  latest_pipeline_run: PipelineRunSummary | null;
  recent_pipeline_runs: PipelineRunSummary[];
};
