"use client";

import { useMemo, useState } from "react";

import { formatDateTime } from "@/lib/date";
import type { EventWithMarkets, Market } from "@/types/market";

const CLOSE_DATE_FORMAT_OPTIONS: Intl.DateTimeFormatOptions = {
  timeZone: "UTC",
  timeZoneName: "short",
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  hourCycle: "h23",
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

function summarizeEvent(event: EventWithMarkets): {
  totalVolume: number;
  totalLiquidity: number;
  nextClose: string | null;
} {
  let totalVolume = 0;
  let totalLiquidity = 0;
  let nextClose: string | null = null;
  let nextCloseMs: number | null = null;

  for (const market of event.markets) {
    if (typeof market.volume_usd === "number" && !Number.isNaN(market.volume_usd)) {
      totalVolume += market.volume_usd;
    }
    if (typeof market.liquidity_usd === "number" && !Number.isNaN(market.liquidity_usd)) {
      totalLiquidity += market.liquidity_usd;
    }
    if (market.close_time) {
      const closeMs = Date.parse(market.close_time);
      if (!Number.isNaN(closeMs) && (nextCloseMs === null || closeMs < nextCloseMs)) {
        nextCloseMs = closeMs;
        nextClose = new Date(closeMs).toISOString();
      }
    }
  }

  return { totalVolume, totalLiquidity, nextClose };
}

function primaryLine(text: string | null | undefined): string | null {
  if (!text) {
    return null;
  }
  const trimmed = text.trim();
  if (!trimmed) {
    return null;
  }
  const firstLine = trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  return firstLine ?? null;
}

export function MarketTable({ events }: { events: EventWithMarkets[] }) {
  const [expandedEvents, setExpandedEvents] = useState<Record<string, boolean>>({});
  const [expandedMarkets, setExpandedMarkets] = useState<Record<string, boolean>>({});
  const rows = useMemo(() => events, [events]);

  if (!rows.length) {
    return (
      <section className="empty-state">
        <strong>No events matched the current filters.</strong>
        <span>Adjust the filters to explore more open Polymarket events.</span>
      </section>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {rows.map((event) => {
        const isExpanded = Boolean(expandedEvents[event.event_id]);
        const { totalVolume, totalLiquidity, nextClose } = summarizeEvent(event);
        const eventDescription = primaryLine(event.description);
        const polymarketEventUrl = event.slug
          ? `https://polymarket.com/event/${event.slug}`
          : null;

        return (
          <section
            key={event.event_id}
            style={{
              border: "1px solid #e2e8f0",
              borderRadius: "0.75rem",
              padding: "1.25rem",
              boxShadow: "0 1px 2px rgba(15, 23, 42, 0.06)",
              backgroundColor: "#fff",
            }}
          >
            <header
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "0.75rem",
                marginBottom: isExpanded ? "1rem" : 0,
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
                  <h2 style={{ fontSize: "1.25rem", margin: 0 }}>
                    {polymarketEventUrl ? (
                      <a
                        href={polymarketEventUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ textDecoration: "underline" }}
                      >
                        {event.title ?? event.slug ?? event.event_id}
                      </a>
                    ) : (
                      event.title ?? event.slug ?? event.event_id
                    )}
                  </h2>
                  <span className="badge">{event.market_count} markets</span>
                </div>
                {eventDescription && (
                  <div style={{ color: "#475569", marginTop: "0.35rem" }}>{eventDescription}</div>
                )}
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "0.5rem",
                    marginTop: "0.75rem",
                    fontSize: "0.85rem",
                    color: "#64748b",
                  }}
                >
                  <span className="badge" style={{ backgroundColor: "#f1f5f9" }}>
                    Total Volume: {formatCurrency(totalVolume)}
                  </span>
                  <span className="badge" style={{ backgroundColor: "#f1f5f9" }}>
                    Total Liquidity: {formatCurrency(totalLiquidity)}
                  </span>
                  <span className="badge" style={{ backgroundColor: "#f1f5f9" }}>
                    Next Close: {nextClose ? formatCloseDate(nextClose) : "-"}
                  </span>
                  {event.start_time && (
                    <span className="badge" style={{ backgroundColor: "#f1f5f9" }}>
                      Event Start: {formatCloseDate(event.start_time)}
                    </span>
                  )}
                </div>
              </div>
              <div>
                <button
                  type="button"
                  onClick={() =>
                    setExpandedEvents((prev) => ({
                      ...prev,
                      [event.event_id]: !isExpanded,
                    }))
                  }
                  style={{
                    padding: "0.5rem 0.75rem",
                    borderRadius: "0.5rem",
                    border: "1px solid #cbd5f5",
                    backgroundColor: isExpanded ? "#1d4ed8" : "#2563eb",
                    color: "white",
                    cursor: "pointer",
                    width: "fit-content",
                  }}
                >
                  {isExpanded ? "Hide markets" : "View markets"}
                </button>
              </div>
            </header>

            {isExpanded && (
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
                    {event.markets.map((market: Market) => {
                      const marketExpanded = Boolean(expandedMarkets[market.market_id]);
                      const description = market.description?.trim() ?? "";
                      const descriptionLine = primaryLine(description);
                      const hasMore = description.length > 0 && descriptionLine !== description;
                      const polymarketMarketUrl = market.slug
                        ? `https://polymarket.com/event/${market.slug}`
                        : null;

                      return (
                        <tr key={market.market_id}>
                          <td>
                            <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>
                              {polymarketMarketUrl ? (
                                <a
                                  href={polymarketMarketUrl}
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
                            {!marketExpanded && descriptionLine && (
                              <div
                                style={{
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  whiteSpace: "nowrap",
                                  fontSize: "0.9rem",
                                  color: "#475569",
                                  marginBottom: hasMore ? "0.25rem" : 0,
                                }}
                              >
                                {descriptionLine}
                              </div>
                            )}
                            {marketExpanded && description && (
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
                            {hasMore && (
                              <button
                                type="button"
                                onClick={() =>
                                  setExpandedMarkets((prev) => ({
                                    ...prev,
                                    [market.market_id]: !marketExpanded,
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
                                {marketExpanded ? "Show less" : "Show more"}
                              </button>
                            )}
                            <div
                              style={{
                                display: "flex",
                                gap: "0.5rem",
                                fontSize: "0.75rem",
                                color: "#94a3b8",
                                marginTop: "0.35rem",
                              }}
                            >
                              {market.category && <span className="badge">{market.category}</span>}
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
            )}
          </section>
        );
      })}
    </div>
  );
}
