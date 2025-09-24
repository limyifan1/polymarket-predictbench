"use client";

import { useMemo } from "react";
import { formatDateTime } from "@/lib/date";
import type { Market } from "@/types/market";

function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatProbability(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function formatDate(value: string | null | undefined): string {
  return formatDateTime(value);
}

export function MarketTable({ markets }: { markets: Market[] }) {
  const rows = useMemo(() => markets, [markets]);

  if (!rows.length) {
    return (
      <section className="empty-state">
        <strong>No markets match the current filters.</strong>
        <span>Adjust the filters to explore more open markets.</span>
      </section>
    );
  }

  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Question</th>
            <th>Close Date</th>
            <th>Volume</th>
            <th>Liquidity</th>
            <th>Top Outcome</th>
            <th>Probability</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((market) => {
            const topOutcome = market.contracts[0];
            return (
              <tr key={market.market_id}>
                <td>
                  <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>{market.question}</div>
                  <div style={{ display: "flex", gap: "0.5rem", fontSize: "0.75rem", color: "#94a3b8" }}>
                    {market.category && <span className="badge">{market.category}</span>}
                    <span>Last sync: {formatDate(market.last_synced_at)}</span>
                  </div>
                </td>
                <td>{formatDate(market.close_time)}</td>
                <td>{formatCurrency(market.volume_usd)}</td>
                <td>{formatCurrency(market.liquidity_usd)}</td>
                <td>{topOutcome?.name ?? "-"}</td>
                <td>{formatProbability(topOutcome?.implied_probability ?? topOutcome?.current_price)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
