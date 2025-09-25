import { MarketFilters } from "@/components/MarketFilters";
import { MarketTable } from "@/components/MarketTable";
import { fetchEvents, parseFilters } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const filters = parseFilters(searchParams);
  const events = await fetchEvents(filters);
  const totalMarkets = events.items.reduce((sum, event) => sum + event.market_count, 0);

  return (
    <main>
      <header style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>Open Polymarket Markets</h1>
        <p style={{ color: "#94a3b8", maxWidth: "60ch" }}>
          Explore live Polymarket events grouped into their underlying markets. Filter by close window, threshold
          liquidity, and sort criteria to surface high-signal venues for experimentation.
        </p>
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
      <section style={{ marginBottom: "1rem", color: "#94a3b8" }}>
        Showing {events.items.length} of {events.total} events spanning {totalMarkets} markets.
      </section>
      <MarketTable events={events.items} />
    </main>
  );
}
