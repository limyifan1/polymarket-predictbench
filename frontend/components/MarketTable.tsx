"use client";

import { useMemo, useState } from "react";
import { formatDateTime } from "@/lib/date";
import type { Market } from "@/types/market";

const CLOSE_DATE_FORMAT_OPTIONS: Intl.DateTimeFormatOptions = {
  timeZone: "UTC",
  timeZoneName: "short",
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
};

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

function formatOutcomePrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return `$${value.toFixed(2)}`;
}

function formatDate(value: string | null | undefined): string {
  return formatDateTime(value);
}

function formatCloseDate(value: string | null | undefined): string {
  return formatDateTime(value, CLOSE_DATE_FORMAT_OPTIONS);
}

export function MarketTable({ markets }: { markets: Market[] }) {
  const [expandedMarkets, setExpandedMarkets] = useState<Record<string, boolean>>({});
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
            <th>Close Date (UTC)</th>
            <th>Volume</th>
            <th>Liquidity</th>
            <th>Outcomes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((market) => {
            const isExpanded = Boolean(expandedMarkets[market.market_id]);
            const description = market.description?.trim() ?? "";
            const primaryDescriptionLine = description
              .split(/\r?\n/)
              .find((line) => line.trim().length > 0);
            const singleLineDescription = primaryDescriptionLine ?? "";
            const hasMoreDescription =
              description.length > 0 && description !== singleLineDescription;
            const polymarketUrl = market.slug
              ? `https://polymarket.com/event/${market.slug}`
              : null;
            return (
              <tr key={market.market_id}>
                <td>
                  <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>
                    {polymarketUrl ? (
                      <a
                        href={polymarketUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ textDecoration: "underline" }}
                      >
                        {market.question}
                      </a>
                    ) : (
                      market.question
                    )}
                  </div>
                  {singleLineDescription && !isExpanded && (
                    <div
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        fontSize: "0.9rem",
                        color: "#475569",
                        marginBottom: hasMoreDescription ? "0.25rem" : 0,
                      }}
                    >
                      {singleLineDescription}
                    </div>
                  )}
                  {isExpanded && description && (
                    <div
                      style={{
                        fontSize: "0.9rem",
                        color: "#475569",
                        marginBottom: "0.25rem",
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {description}
                    </div>
                  )}
                  {hasMoreDescription && (
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedMarkets((prev) => ({
                          ...prev,
                          [market.market_id]: !isExpanded,
                        }))
                      }
                      style={{
                        border: "none",
                        background: "none",
                        padding: 0,
                        color: "#3b82f6",
                        cursor: "pointer",
                        fontSize: "0.8rem",
                      }}
                    >
                      {isExpanded ? "Show less" : "Show more"}
                    </button>
                  )}
                  <div
                    style={{
                      display: "flex",
                      gap: "0.5rem",
                      fontSize: "0.75rem",
                      color: "#94a3b8",
                    }}
                  >
                    {market.category && (
                      <span className="badge">{market.category}</span>
                    )}
                    <span>Last sync: {formatDate(market.last_synced_at)}</span>
                  </div>
                </td>
                <td>{formatCloseDate(market.close_time)}</td>
                <td>{formatCurrency(market.volume_usd)}</td>
                <td>{formatCurrency(market.liquidity_usd)}</td>
                <td>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.15rem",
                      fontSize: "0.85rem",
                    }}
                  >
                    {market.contracts.map((contract) => (
                      <span key={contract.contract_id}>
                        <strong>{contract.name}</strong>
                        {" — "}
                        {formatOutcomePrice(contract.current_price)}
                        {contract.implied_probability !== null &&
                        contract.implied_probability !== undefined ? (
                          <> ({formatProbability(contract.implied_probability)})</>
                        ) : null}
                      </span>
                    ))}
                    {!market.contracts.length && <span>-</span>}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
