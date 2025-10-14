import Link from "next/link";

import { parseDate } from "@/lib/date";

export type FilterState = {
  close_after?: string | null;
  close_before?: string | null;
  min_volume?: number | null;
  sort?: string;
  order?: string;
  dataset?: "local" | "production";
  resolved_only?: boolean;
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
      <div className="filters__header">
        <div>
          <h2 className="filters__title">Filter live markets</h2>
          <p className="filters__subtitle">
            Combine time bounds, minimum depth, and sort preferences to surface the most actionable events.
          </p>
        </div>
        <Link href="/" className="button button--ghost">
          Reset all
        </Link>
      </div>
      <div className="filters__grid">
        <label className="field">
          <span className="field__label">Dataset</span>
          <select className="field__input" name="dataset" defaultValue={initial.dataset ?? "local"}>
            <option value="local">Local dataset</option>
            <option value="production">Production (Supabase)</option>
          </select>
        </label>
        <label className="field">
          <span className="field__label">Close after</span>
          <input
            className="field__input"
            type="date"
            name="close_after"
            defaultValue={isoToDateInput(initial.close_after ?? null)}
          />
        </label>
        <label className="field">
          <span className="field__label">Close before</span>
          <input
            className="field__input"
            type="date"
            name="close_before"
            defaultValue={isoToDateInput(initial.close_before ?? null)}
          />
        </label>
        <label className="field">
          <span className="field__label">Min volume (USD)</span>
          <input
            className="field__input"
            type="number"
            name="min_volume"
            min={0}
            step={1000}
            placeholder="10000"
            defaultValue={initial.min_volume ?? undefined}
          />
        </label>
        <label className="field">
          <span className="field__label">Sort by</span>
          <select className="field__input" name="sort" defaultValue={initial.sort ?? "close_time"}>
            <option value="close_time">Close date</option>
            <option value="volume_usd">Volume</option>
            <option value="liquidity_usd">Liquidity</option>
            <option value="last_synced_at">Last synced</option>
          </select>
        </label>
        <label className="field">
          <span className="field__label">Order</span>
          <select className="field__input" name="order" defaultValue={initial.order ?? "asc"}>
            <option value="asc">Ascending</option>
            <option value="desc">Descending</option>
          </select>
        </label>
      </div>
      <div className="filters__actions">
        <label className="filters__checkbox">
          <input
            className="filters__checkbox-input"
            type="checkbox"
            name="resolved_only"
            value="1"
            defaultChecked={Boolean(initial.resolved_only)}
          />
          <span>Show resolved events only</span>
        </label>
        <button type="submit" className="button button--primary">
          Apply filters
        </button>
      </div>
    </form>
  );
}
