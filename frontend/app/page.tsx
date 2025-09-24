import { MarketFilters } from "@/components/MarketFilters";
import { MarketTable } from "@/components/MarketTable";
import { fetchMarkets, parseFilters } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const filters = parseFilters(searchParams);
  const markets = await fetchMarkets(filters);

  return (
    <main>
      <header style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>Open Polymarket Markets</h1>
        <p style={{ color: "#94a3b8", maxWidth: "60ch" }}>
          Explore live markets sourced from Polymarket. Filter by close window, threshold liquidity, and order by
          liquidity or volume to identify promising opportunities for LLM forecasting experiments.
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
        Showing {markets.items.length} of {markets.total} markets.
      </section>
      <MarketTable markets={markets.items} />
    </main>
  );
}
