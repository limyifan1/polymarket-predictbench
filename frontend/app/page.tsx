import { DatasetOverviewPanel } from "@/components/DatasetOverviewPanel";
import { MarketFilters } from "@/components/MarketFilters";
import { MarketTable } from "@/components/MarketTable";
import { PageTabs } from "@/components/PageTabs";
import { fetchDatasetOverview, fetchEvents, parseFilters } from "@/lib/api";

export const dynamic = "force-dynamic";

function formatSummaryCurrency(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }

  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatCoverage(value: number, total: number): string {
  if (!total || total <= 0) {
    return "-";
  }
  const ratio = (value / total) * 100;
  return `${ratio.toFixed(ratio < 10 ? 1 : 0)}%`;
}

export default async function Home({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const filters = parseFilters(searchParams);
  const viewParam = searchParams.view;
  const view = typeof viewParam === "string" && viewParam.toLowerCase() === "overview" ? "overview" : "explorer";

  const events = view === "overview" ? null : await fetchEvents(filters);
  const overview = view === "overview" ? await fetchDatasetOverview(filters.dataset) : null;

  const totalMarkets = events?.items.reduce((sum, event) => sum + event.market_count, 0) ?? 0;
  const datasetLabel = filters.dataset === "production" ? "Production (Supabase)" : "Local dataset";
  const aggregate = events
    ? events.items.reduce(
        (acc, event) => {
          for (const market of event.markets) {
            if (typeof market.volume_usd === "number" && !Number.isNaN(market.volume_usd)) {
              acc.volume += market.volume_usd;
            }
            if (typeof market.liquidity_usd === "number" && !Number.isNaN(market.liquidity_usd)) {
              acc.liquidity += market.liquidity_usd;
            }
          }

          return acc;
        },
        { volume: 0, liquidity: 0 },
      )
    : { volume: 0, liquidity: 0 };

  return (
    <main className="page">
      <header className="page__intro">
        <div className="page__intro-text">
          <h1 className="page__title">Polymarket Market Explorer</h1>
          <p className="page__subtitle">
            Assess live Polymarket questions grouped by event. Dial in on signal by filtering for relevant time windows,
            minimum depth, and market freshness.
          </p>
          <span
            className="badge badge--context"
            data-tone={filters.dataset === "production" ? "production" : "local"}
            aria-label="Active dataset"
          >
            {datasetLabel}
          </span>
        </div>
        <dl className="page__metrics" aria-label="Current dataset summary">
          {view === "explorer" && events ? (
            <>
              <div className="metric-card">
                <dt className="metric-card__label">Visible events</dt>
                <dd className="metric-card__value">{events.items.length}</dd>
                <dd className="metric-card__hint">of {events.total} total</dd>
              </div>
              <div className="metric-card">
                <dt className="metric-card__label">Underlying markets</dt>
                <dd className="metric-card__value">{totalMarkets}</dd>
              </div>
              <div className="metric-card">
                <dt className="metric-card__label">Tracked volume</dt>
                <dd className="metric-card__value">{formatSummaryCurrency(aggregate.volume)}</dd>
                <dd className="metric-card__hint">Liquidity {formatSummaryCurrency(aggregate.liquidity)}</dd>
              </div>
            </>
          ) : overview ? (
            <>
              <div className="metric-card">
                <dt className="metric-card__label">Events tracked</dt>
                <dd className="metric-card__value">{overview.total_events}</dd>
                <dd className="metric-card__hint">
                  Research {formatCoverage(overview.events_with_research, overview.total_events)}
                </dd>
              </div>
              <div className="metric-card">
                <dt className="metric-card__label">Research artifacts</dt>
                <dd className="metric-card__value">{overview.total_research_artifacts}</dd>
                <dd className="metric-card__hint">{overview.events_with_research} covered events</dd>
              </div>
              <div className="metric-card">
                <dt className="metric-card__label">Forecast outputs</dt>
                <dd className="metric-card__value">{overview.total_forecast_results}</dd>
                <dd className="metric-card__hint">
                  Forecast {formatCoverage(overview.events_with_forecasts, overview.total_events)}
                </dd>
              </div>
            </>
          ) : null}
        </dl>
      </header>
      <PageTabs view={view} dataset={filters.dataset ?? "local"} searchParams={searchParams} />
      {view === "explorer" && events ? (
        <>
          <MarketFilters
            initial={{
              close_after: filters.close_after ?? null,
              close_before: filters.close_before ?? null,
              min_volume: filters.min_volume ?? null,
              sort: filters.sort,
              order: filters.order,
              dataset: filters.dataset,
            }}
          />
          <MarketTable events={events.items} />
        </>
      ) : overview ? (
        <DatasetOverviewPanel overview={overview} />
      ) : null}
    </main>
  );
}
