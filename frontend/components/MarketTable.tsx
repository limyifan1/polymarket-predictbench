"use client";

import { useMemo, useState } from "react";

import { formatDateTime } from "@/lib/date";
import type {
  EventWithMarkets,
  ForecastResult,
  Market,
  ResearchArtifact,
} from "@/types/market";

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

type ResearchSource = {
  title: string;
  url: string;
  snippet?: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function extractResearchSummary(payload: Record<string, unknown> | null | undefined): string | null {
  if (!isRecord(payload)) {
    return null;
  }
  const summary = payload.summary;
  return typeof summary === "string" && summary.trim().length ? summary.trim() : null;
}

function extractResearchConfidence(payload: Record<string, unknown> | null | undefined): string | null {
  if (!isRecord(payload)) {
    return null;
  }
  const confidence = payload.confidence;
  if (typeof confidence === "string" && confidence.trim()) {
    return confidence.trim();
  }
  return null;
}

function extractResearchInsights(payload: Record<string, unknown> | null | undefined): string[] {
  if (!isRecord(payload)) {
    return [];
  }
  const insights = payload.key_insights;
  if (!Array.isArray(insights)) {
    return [];
  }
  return insights
    .map((item) => {
      if (typeof item === "string" && item.trim()) {
        return item.trim();
      }
      if (isRecord(item)) {
        const candidates = [item.insight, item.summary, item.text];
        for (const candidate of candidates) {
          if (typeof candidate === "string" && candidate.trim()) {
            return candidate.trim();
          }
        }
      }
      return null;
    })
    .filter((value): value is string => typeof value === "string" && value.length > 0);
}

function extractResearchSources(payload: Record<string, unknown> | null | undefined): ResearchSource[] {
  if (!isRecord(payload)) {
    return [];
  }
  const sources = payload.sources;
  if (!Array.isArray(sources)) {
    return [];
  }
  return sources
    .map((entry) => {
      if (!isRecord(entry)) {
        return null;
      }
      const url = typeof entry.url === "string" ? entry.url : null;
      const title = typeof entry.title === "string" ? entry.title : null;
      if (!url || !title) {
        return null;
      }
      const snippet = typeof entry.snippet === "string" ? entry.snippet : null;
      return { title, url, snippet } satisfies ResearchSource;
    })
    .filter((value): value is ResearchSource => Boolean(value));
}

function extractOutcomePrices(
  payload: Record<string, unknown> | null | undefined,
): Array<{ outcome: string; price: number }> {
  if (!isRecord(payload)) {
    return [];
  }
  const data = payload.outcomePrices;
  if (!isRecord(data)) {
    return [];
  }
  return Object.entries(data)
    .map(([outcome, value]) => {
      if (typeof value === "number") {
        return { outcome, price: value };
      }
      if (typeof value === "string") {
        const parsed = Number.parseFloat(value);
        if (!Number.isNaN(parsed)) {
          return { outcome, price: parsed };
        }
      }
      return null;
    })
    .filter((entry): entry is { outcome: string; price: number } => Boolean(entry));
}

function extractForecastReasoning(payload: Record<string, unknown> | null | undefined): string | null {
  if (!isRecord(payload)) {
    return null;
  }
  const reasoning = payload.reasoning;
  if (typeof reasoning === "string" && reasoning.trim()) {
    return reasoning.trim();
  }
  return null;
}

function formatUrlHost(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./, "");
  } catch (error) {
    return url;
  }
}

function EventResearch({ research }: { research: ResearchArtifact[] }) {
  if (!research.length) {
    return null;
  }

  return (
    <section className="event-research" aria-label="Experiment research summaries">
      <header className="event-research__header">
        <h4 className="event-research__title">Research briefs</h4>
        <p className="event-research__subtitle">
          Synthesized evidence produced during the latest research-stage experiment runs for this event.
        </p>
      </header>
      <div className="event-research__grid">
        {research.map((artifact) => {
          const summary = extractResearchSummary(artifact.payload ?? null);
          const insights = extractResearchInsights(artifact.payload ?? null).slice(0, 4);
          const sources = extractResearchSources(artifact.payload ?? null).slice(0, 4);
          const confidence = extractResearchConfidence(artifact.payload ?? null);
          const key = artifact.artifact_id ?? `${artifact.descriptor.experiment_name}:${artifact.descriptor.variant_name}`;

          return (
            <article key={key} className="research-card">
              <header className="research-card__header">
                <div className="research-card__heading">
                  <span className="badge">
                    {artifact.descriptor.variant_name} v{artifact.descriptor.variant_version}
                  </span>
                  <span className="research-card__experiment">
                    {artifact.descriptor.experiment_name} · stage {artifact.descriptor.stage}
                  </span>
                </div>
                <div className="research-card__meta">
                  <span>Run {artifact.run.run_id}</span>
                  <span>Updated {formatDateTime(artifact.updated_at)}</span>
                  {artifact.pipeline_run ? (
                    <span>
                      Pipeline {artifact.pipeline_run.run_date} ({artifact.pipeline_run.environment ?? "local"})
                    </span>
                  ) : null}
                </div>
              </header>
              {summary && <p className="research-card__summary">{summary}</p>}
              {confidence && <p className="research-card__confidence">Confidence: {confidence}</p>}
              {insights.length > 0 && (
                <div className="research-card__section">
                  <h5>Key insights</h5>
                  <ul className="research-card__list">
                    {insights.map((insight, index) => (
                      <li key={`${key}-insight-${index}`}>{insight}</li>
                    ))}
                  </ul>
                </div>
              )}
              {sources.length > 0 && (
                <div className="research-card__section">
                  <h5>Primary sources</h5>
                  <ul className="research-card__sources">
                    {sources.map((source, index) => (
                      <li key={`${key}-source-${index}`}>
                        <a href={source.url} target="_blank" rel="noopener noreferrer">
                          {source.title}
                        </a>
                        <span className="research-card__source-host">{formatUrlHost(source.url)}</span>
                        {source.snippet && <p className="research-card__source-snippet">{source.snippet}</p>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {artifact.artifact_uri && (
                <a
                  className="research-card__artifact"
                  href={artifact.artifact_uri}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  View full artifact
                </a>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function MarketForecasts({ results }: { results: ForecastResult[] }) {
  if (!results.length) {
    return null;
  }

  return (
    <section className="market-forecasts" aria-label="Experiment forecast results">
      <h5 className="market-forecasts__title">Model forecasts</h5>
      <div className="market-forecasts__list">
        {results.map((result) => {
          const key = `${result.descriptor.experiment_name}:${result.descriptor.variant_name}:${result.recorded_at}`;
          const prices = extractOutcomePrices(result.payload ?? null);
          const reasoning = extractForecastReasoning(result.payload ?? null);

          return (
            <article key={key} className="forecast-card">
              <header className="forecast-card__header">
                <div className="forecast-card__heading">
                  <span className="badge">
                    {result.descriptor.variant_name} v{result.descriptor.variant_version}
                  </span>
                  <span className="forecast-card__experiment">{result.descriptor.experiment_name}</span>
                </div>
                <div className="forecast-card__meta">
                  <span>Run {result.run.run_id}</span>
                  <span>{result.run.status}</span>
                  <span>Updated {formatDateTime(result.recorded_at)}</span>
                </div>
              </header>
              {result.score !== null && result.score !== undefined && !Number.isNaN(result.score) && (
                <p className="forecast-card__score">Calibration score: {result.score.toFixed(3)}</p>
              )}
              {prices.length > 0 && (
                <table className="forecast-card__table">
                  <thead>
                    <tr>
                      <th scope="col">Outcome</th>
                      <th scope="col">Price</th>
                      <th scope="col">Implied</th>
                    </tr>
                  </thead>
                  <tbody>
                    {prices.map((item) => (
                      <tr key={`${key}-${item.outcome}`}>
                        <td>{item.outcome}</td>
                        <td>${item.price.toFixed(3)}</td>
                        <td>{formatProbability(item.price)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {reasoning && <p className="forecast-card__reasoning">{reasoning}</p>}
              {result.artifact_uri && (
                <a
                  className="forecast-card__artifact"
                  href={result.artifact_uri}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Review submission payload
                </a>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
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

                <EventResearch research={event.research} />

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

                          <MarketForecasts results={market.experiment_results} />
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
