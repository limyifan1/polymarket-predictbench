import Link from "next/link";

import { parseDate } from "@/lib/date";

export type FilterState = {
  close_after?: string | null;
  close_before?: string | null;
  min_volume?: number | null;
  sort?: string;
  order?: string;
};

function isoToDateInput(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) {
    return "";
  }
  return date.toISOString().split("T")[0] ?? "";
}

export function MarketFilters({ initial }: { initial: FilterState }) {
  return (
    <form className="filters" method="get">
      <label>
        Close After
        <input type="date" name="close_after" defaultValue={isoToDateInput(initial.close_after ?? null)} />
      </label>
      <label>
        Close Before
        <input type="date" name="close_before" defaultValue={isoToDateInput(initial.close_before ?? null)} />
      </label>
      <label>
        Min Volume (USD)
        <input
          type="number"
          name="min_volume"
          min={0}
          step={1000}
          placeholder="10000"
          defaultValue={initial.min_volume ?? undefined}
        />
      </label>
      <label>
        Sort By
        <select name="sort" defaultValue={initial.sort ?? "close_time"}>
          <option value="close_time">Close Date</option>
          <option value="volume_usd">Volume</option>
          <option value="liquidity_usd">Liquidity</option>
          <option value="last_synced_at">Last Synced</option>
        </select>
      </label>
      <label>
        Order
        <select name="order" defaultValue={initial.order ?? "asc"}>
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
      </label>
      <div style={{ display: "flex", gap: "0.75rem", alignItems: "flex-end" }}>
        <button type="submit">Apply Filters</button>
        <Link href="/" className="badge" style={{ textDecoration: "none", alignSelf: "center" }}>
          Reset
        </Link>
      </div>
    </form>
  );
}
