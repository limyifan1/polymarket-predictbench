import { MarketFilters } from "@/components/MarketFilters";
import { MarketTable } from "@/components/MarketTable";
import { fetchEvents, parseFilters } from "@/lib/api";

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

export default async function Home({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const filters = parseFilters(searchParams);
  const events = await fetchEvents(filters);
  const totalMarkets = events.items.reduce((sum, event) => sum + event.market_count, 0);
  const aggregate = events.items.reduce(
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
  );

  return (
    <main className="page">
      <header className="page__intro">
        <div className="page__intro-text">
          <h1 className="page__title">Polymarket Market Explorer</h1>
          <p className="page__subtitle">
            Assess live Polymarket questions grouped by event. Dial in on signal by filtering for relevant time windows,
            minimum depth, and market freshness.
          </p>
        </div>
        <dl className="page__metrics" aria-label="Current dataset summary">
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
        </dl>
      </header>
      <MarketFilters
        initial={{
          close_after: filters.close_after ?? null,
          close_before: filters.close_before ?? null,
          min_volume: filters.min_volume ?? null,
          sort: filters.sort,
          order: filters.order,
        }}
      />
      <MarketTable events={events.items} />
    </main>
  );
}
