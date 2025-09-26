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
  const [expandedMarkets, setExpandedMarkets] = useState<Record<string, boolean>>({});
  const rows = useMemo(() => events, [events]);

  return (
    <section className="market-results">
      <header className="market-results__header">
        <h2 className="section-title">Event breakdown</h2>
        <p className="section-subtitle">
          Every event includes the full set of markets so you can compare close times, depth, and pricing without
          extra clicks.
        </p>
      </header>

      {!rows.length ? (
        <div className="empty-state">
          <strong>No events matched the current filters.</strong>
          <span>Adjust the filters to explore more open Polymarket events.</span>
        </div>
      ) : (
        <div className="market-results__list">
          {rows.map((event) => {
            const { totalVolume, totalLiquidity, nextClose } = summarizeEvent(event);
            const eventDescription = primaryLine(event.description);
            const polymarketEventUrl = event.slug ? `https://polymarket.com/event/${event.slug}` : null;

            return (
              <article
                key={event.event_id}
                className="event-card"
              >
                <header className="event-card__header">
                  <div className="event-card__title-group">
                    <h3 className="event-card__title">
                      {polymarketEventUrl ? (
                        <a
                          href={polymarketEventUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="event-card__link"
                        >
                          {event.title ?? event.slug ?? event.event_id}
                        </a>
                      ) : (
                        event.title ?? event.slug ?? event.event_id
                      )}
                    </h3>
                    <span className="badge">{event.market_count} markets</span>
                  </div>
                  {eventDescription && <p className="event-card__description">{eventDescription}</p>}
                  <dl className="event-card__stats">
                    <div>
                      <dt>Total volume</dt>
                      <dd>{formatCurrency(totalVolume)}</dd>
                    </div>
                    <div>
                      <dt>Total liquidity</dt>
                      <dd>{formatCurrency(totalLiquidity)}</dd>
                    </div>
                    <div>
                      <dt>Next close</dt>
                      <dd>{nextClose ? formatCloseDate(nextClose) : "-"}</dd>
                    </div>
                    {event.start_time && (
                      <div>
                        <dt>Event start</dt>
                        <dd>{formatCloseDate(event.start_time)}</dd>
                      </div>
                    )}
                  </dl>
                </header>

                <div className="event-card__markets event-card__markets--grid">
                  <div className="market-grid">
                    {event.markets.map((market: Market) => {
                      const marketExpanded = Boolean(expandedMarkets[market.market_id]);
                      const description = market.description?.trim() ?? "";
                      const descriptionLine = primaryLine(description);
                      const hasMore = description.length > 0 && descriptionLine !== description;
                      const polymarketMarketUrl = market.slug ? `https://polymarket.com/event/${market.slug}` : null;

                      return (
                        <div key={market.market_id} className="market-card">
                          <header className="market-card__header">
                            <h4 className="market-card__title">
                              {polymarketMarketUrl ? (
                                <a href={polymarketMarketUrl} target="_blank" rel="noopener noreferrer">
                                  {market.question}
                                </a>
                              ) : (
                                market.question
                              )}
                            </h4>
                            <div className="market-card__tags">
                              {market.category && <span className="badge">{market.category}</span>}
                              <span className="market-card__sync">Last sync {formatDate(market.last_synced_at)}</span>
                            </div>
                          </header>

                          <div className="market-card__summary">
                            {!marketExpanded && descriptionLine && (
                              <p className="market-card__excerpt">{descriptionLine}</p>
                            )}
                            {marketExpanded && description && (
                              <p className="market-card__details">{description}</p>
                            )}
                            {hasMore && (
                              <button
                                type="button"
                                className="market-row__toggle"
                                data-expanded={marketExpanded ? "true" : "false"}
                                aria-expanded={marketExpanded}
                                onClick={() =>
                                  setExpandedMarkets((prev) => ({
                                    ...prev,
                                    [market.market_id]: !marketExpanded,
                                  }))
                                }
                              >
                                {marketExpanded ? "Show less" : "Show more"}
                              </button>
                            )}
                          </div>

                          <dl className="market-card__stats">
                            <div>
                              <dt>Close (UTC)</dt>
                              <dd>{formatCloseDate(market.close_time)}</dd>
                            </div>
                            <div>
                              <dt>Volume</dt>
                              <dd>{formatCurrency(market.volume_usd)}</dd>
                            </div>
                            <div>
                              <dt>Liquidity</dt>
                              <dd>{formatCurrency(market.liquidity_usd)}</dd>
                            </div>
                          </dl>

                          <ul className="market-card__outcomes">
                            {market.contracts.map((contract) => (
                              <li key={contract.contract_id}>
                                <span className="market-card__outcome-name">{contract.name}</span>
                                <span className="market-card__outcome-value">
                                  {formatOutcomePrice(contract.current_price)}
                                  {contract.implied_probability !== null &&
                                  contract.implied_probability !== undefined ? (
                                    <>
                                      {" "}
                                      <span className="market-card__probability">
                                        {formatProbability(contract.implied_probability)}
                                      </span>
                                    </>
                                  ) : null}
                                </span>
                              </li>
                            ))}
                            {!market.contracts.length && <li className="market-row__outcome-empty">-</li>}
                          </ul>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
