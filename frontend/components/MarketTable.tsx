"use client";

import { useMemo, useState } from "react";

import { formatDateTime } from "@/lib/date";
import type {
  Contract,
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

function formatProbabilityDifference(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  const absValue = Math.abs(value);
  const prefix = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${prefix}${absValue.toFixed(1)} pp`;
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

function normalizeString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length ? trimmed : null;
}

function normalizeOutcomeKey(value: string | null | undefined): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  return trimmed.toLowerCase();
}

function normalizeConfidence(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const lower = trimmed.toLowerCase();
  return lower.replace(/\b\w/g, (character) => character.toUpperCase());
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
      const snippet = normalizeString(entry.snippet);
      return { title, url, snippet } satisfies ResearchSource;
    })
    .filter((value): value is ResearchSource => Boolean(value));
}

type ResearchCardContent = {
  summary: string | null;
  confidence: string | null;
  insights: string[];
  sources: ResearchSource[];
};

function timelineEntriesToInsights(
  label: "Upcoming" | "Past",
  entries: unknown,
): string[] {
  if (!Array.isArray(entries)) {
    return [];
  }

  return entries
    .map((entry) => {
      if (!isRecord(entry)) {
        return null;
      }

      const title = normalizeString(entry.title);
      const impact = normalizeString(entry.impact);
      const notes = normalizeString(entry.notes);
      const dateRaw = normalizeString(entry.date);
      const formattedDate = dateRaw ? formatDateTime(dateRaw) : null;

      const descriptorParts = [title, impact, notes].filter(Boolean);
      if (!descriptorParts.length) {
        return null;
      }

      const labelParts = [label];
      if (formattedDate && formattedDate !== "-") {
        labelParts.push(formattedDate);
      } else if (dateRaw) {
        labelParts.push(dateRaw);
      }

      return `${labelParts.join(" · ")}: ${descriptorParts.join(" — ")}`;
    })
    .filter((value): value is string => Boolean(value));
}

function buildResearchCardContent(artifact: ResearchArtifact): ResearchCardContent {
  const payload = artifact.payload ?? null;
  let summary = extractResearchSummary(payload);
  let confidence = extractResearchConfidence(payload);
  let insights = extractResearchInsights(payload);
  let sources = extractResearchSources(payload);

  const experimentNameRaw = artifact.descriptor.experiment_name;
  const experimentName = experimentNameRaw.split(":").at(-1) ?? experimentNameRaw;

  if (experimentName === "superforecaster_briefing" && isRecord(payload)) {
    const summaryParts: string[] = [];
    const referenceClass = normalizeString(payload.reference_class);
    if (referenceClass) {
      summaryParts.push(`Reference class: ${referenceClass}`);
    }

    const baseRateRaw = payload.base_rate;
    if (isRecord(baseRateRaw)) {
      const probability = typeof baseRateRaw.probability === "number" ? formatProbability(baseRateRaw.probability) : null;
      const source = normalizeString(baseRateRaw.source);
      const notes = normalizeString(baseRateRaw.notes);
      const probabilityHint = probability && probability !== "-" ? probability : null;
      const baseRateParts = [probabilityHint, source].filter(Boolean);
      if (baseRateParts.length) {
        summaryParts.push(`Base rate: ${baseRateParts.join(" · ")}`);
      }
      if (notes) {
        summaryParts.push(notes);
      }
    }

    if (!summary && summaryParts.length) {
      summary = summaryParts.join(" • ");
    }

    const scenarioInsights = Array.isArray(payload.scenario_decomposition)
      ? payload.scenario_decomposition
          .map((entry) => {
            if (!isRecord(entry)) {
              return null;
            }
            const name = normalizeString(entry.name);
            const description = normalizeString(entry.description);
            const probability =
              typeof entry.probability === "number" ? formatProbability(entry.probability) : null;
            const impact = normalizeString(entry.impact);
            const descriptorParts = [description, impact].filter(Boolean);
            const descriptor = descriptorParts.join(" — ");
            const probabilityHint = probability && probability !== "-" ? probability : null;
            const details = probabilityHint ? ` (${probabilityHint})` : "";

            if (name && descriptor) {
              return `${name}: ${descriptor}${details}`;
            }
            if (name) {
              return `${name}${details}`;
            }
            if (descriptor) {
              return `${descriptor}${details}`;
            }
            return null;
          })
          .filter((value): value is string => Boolean(value))
      : [];

    const uncertaintyInsights = Array.isArray(payload.key_uncertainties)
      ? payload.key_uncertainties
          .map((item) => normalizeString(item))
          .filter((value): value is string => Boolean(value))
          .map((value) => `Uncertainty: ${value}`)
      : [];

    const triggerInsights = Array.isArray(payload.update_triggers)
      ? payload.update_triggers
          .map((entry) => {
            if (!isRecord(entry)) {
              return null;
            }
            const indicator = normalizeString(entry.indicator);
            if (!indicator) {
              return null;
            }
            const direction = normalizeString(entry.direction);
            const threshold = normalizeString(entry.threshold);
            const details = [direction, threshold].filter(Boolean).join(" · ");
            return details ? `Trigger: ${indicator} (${details})` : `Trigger: ${indicator}`;
          })
          .filter((value): value is string => Boolean(value))
      : [];

    const customInsights = [...scenarioInsights, ...uncertaintyInsights, ...triggerInsights];
    if (customInsights.length) {
      insights = customInsights;
    }

    if (!confidence) {
      const rawConfidence = normalizeString(payload.confidence);
      confidence = rawConfidence ?? null;
    }
  } else if (experimentName === "atlas_research_sweep" && isRecord(payload)) {
    const bullishEntries = Array.isArray(payload.bullish)
      ? payload.bullish
          .map((item) => normalizeString(item))
          .filter((value): value is string => Boolean(value))
      : [];
    const bearishEntries = Array.isArray(payload.bearish)
      ? payload.bearish
          .map((item) => normalizeString(item))
          .filter((value): value is string => Boolean(value))
      : [];
    const riskEntries = Array.isArray(payload.key_risks)
      ? payload.key_risks
          .map((item) => normalizeString(item))
          .filter((value): value is string => Boolean(value))
      : [];

    const summaryParts: string[] = [];
    const counts: string[] = [];
    if (bullishEntries.length) {
      counts.push(`${bullishEntries.length} bullish`);
    }
    if (bearishEntries.length) {
      counts.push(`${bearishEntries.length} bearish`);
    }
    if (riskEntries.length) {
      counts.push(`${riskEntries.length} risks`);
    }
    if (counts.length) {
      summaryParts.push(`Highlights: ${counts.join(" · ")}`);
    }

    const generatedAt = normalizeString(payload.generated_at);
    if (generatedAt) {
      const formatted = formatDateTime(generatedAt);
      if (formatted && formatted !== "-") {
        summaryParts.push(`Generated ${formatted}`);
      }
    }

    if (!summary) {
      if (summaryParts.length) {
        summary = summaryParts.join(" • ");
      } else {
        summary = "Balanced evidence sweep";
      }
    }

    const customInsights = [
      ...bullishEntries.map((value) => `Bullish: ${value}`),
      ...bearishEntries.map((value) => `Bearish: ${value}`),
      ...riskEntries.map((value) => `Risk: ${value}`),
    ];

    if (customInsights.length) {
      insights = customInsights;
    }
  } else if (experimentName === "horizon_signal_timeline" && isRecord(payload)) {
    const generatedAt = normalizeString(payload.generated_at);
    if (!summary && generatedAt) {
      const formatted = formatDateTime(generatedAt);
      summary = formatted && formatted !== "-" ? `Timeline refreshed ${formatted}` : `Timeline refreshed ${generatedAt}`;
    }

    const customInsights = [
      ...timelineEntriesToInsights("Upcoming", payload.upcoming),
      ...timelineEntriesToInsights("Past", payload.past),
    ];

    if (customInsights.length) {
      insights = customInsights;
    }
  }

  return {
    summary,
    confidence: normalizeConfidence(confidence),
    insights,
    sources,
  } satisfies ResearchCardContent;
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

function EventResearch({ research, eventId }: { research: ResearchArtifact[]; eventId: string }) {
  const [collapsed, setCollapsed] = useState(false);

  if (!research.length) {
    return null;
  }

  const bodyId = `event-research-body-${eventId}`;

  return (
    <section
      className={`event-research${collapsed ? " event-research--collapsed" : ""}`}
      aria-label="Experiment research summaries"
      data-collapsed={collapsed ? "true" : "false"}
    >
      <header className="event-research__header">
        <div className="event-research__intro">
          <h4 className="event-research__title">Research briefs</h4>
          <p className="event-research__subtitle">
            Synthesized evidence produced during the latest research-stage experiment runs for this event.
          </p>
        </div>
        <button
          type="button"
          className="event-research__toggle"
          aria-expanded={!collapsed}
          aria-controls={bodyId}
          onClick={() => setCollapsed((prev) => !prev)}
        >
          {collapsed ? "Show briefs" : "Hide briefs"}
        </button>
      </header>
      <div className="event-research__body" id={bodyId} hidden={collapsed}>
        <div className="event-research__grid">
          {research.map((artifact) => {
            const content = buildResearchCardContent(artifact);
            const summary = content.summary;
            const insights = content.insights.slice(0, 4);
            const sources = content.sources.slice(0, 4);
            const confidence = content.confidence;
            const key =
              artifact.artifact_id ?? `${artifact.descriptor.experiment_name}:${artifact.descriptor.variant_name}`;

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
      </div>
    </section>
  );
}

function MarketForecasts({
  results,
  contracts,
}: {
  results: ForecastResult[];
  contracts: Contract[];
}) {
  const marketProbabilityByOutcome = useMemo(() => {
    const map = new Map<string, number>();
    for (const contract of contracts) {
      if (contract.implied_probability === null || contract.implied_probability === undefined) {
        continue;
      }
      if (Number.isNaN(contract.implied_probability)) {
        continue;
      }
      const key = normalizeOutcomeKey(contract.name);
      if (!key) {
        continue;
      }
      map.set(key, contract.implied_probability);
    }
    return map;
  }, [contracts]);

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
                      <th scope="col">Market</th>
                      <th scope="col">Δ vs market</th>
                    </tr>
                  </thead>
                  <tbody>
                    {prices.map((item) => {
                      const outcomeKey = normalizeOutcomeKey(item.outcome);
                      const marketProbability = outcomeKey ? marketProbabilityByOutcome.get(outcomeKey) ?? null : null;
                      const forecastProbability = Number.isFinite(item.price) ? item.price : null;
                      const probabilityDifference =
                        marketProbability === null || marketProbability === undefined || forecastProbability === null
                          ? null
                          : (forecastProbability - marketProbability) * 100;
                      const differenceDirection =
                        probabilityDifference === null
                          ? null
                          : probabilityDifference > 0
                          ? "positive"
                          : probabilityDifference < 0
                          ? "negative"
                          : "neutral";

                        return (
                        <tr key={`${key}-${item.outcome}`}>
                          <td>{item.outcome}</td>
                          <td>${item.price.toFixed(3)}</td>
                          <td>{formatProbability(forecastProbability)}</td>
                          <td>{formatProbability(marketProbability)}</td>
                          <td>
                            {probabilityDifference === null ? (
                              "-"
                            ) : (
                              <span
                                className="forecast-card__delta"
                                data-direction={differenceDirection ?? undefined}
                              >
                                {formatProbabilityDifference(probabilityDifference)}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
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
  const [collapsedEvents, setCollapsedEvents] = useState<Record<string, boolean>>({});
  const [collapsedMarkets, setCollapsedMarkets] = useState<Record<string, boolean>>({});
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
            const eventCollapsed = Boolean(collapsedEvents[event.event_id]);
            const eventBodyId = `event-card-body-${event.event_id}`;

            return (
              <article
                key={event.event_id}
                className={`event-card${eventCollapsed ? " event-card--collapsed" : ""}`}
                data-collapsed={eventCollapsed ? "true" : "false"}
              >
                <header className="event-card__header">
                  <div className="event-card__title-row">
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
                    <button
                      type="button"
                      className="event-card__toggle"
                      aria-expanded={!eventCollapsed}
                      aria-controls={eventBodyId}
                      onClick={() =>
                        setCollapsedEvents((prev) => ({
                          ...prev,
                          [event.event_id]: !eventCollapsed,
                        }))
                      }
                    >
                      {eventCollapsed ? "Show event" : "Hide event"}
                    </button>
                  </div>
                </header>

                <div className="event-card__body" id={eventBodyId} hidden={eventCollapsed}>
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

                  <EventResearch research={event.research} eventId={event.event_id} />

                  <div className="event-card__markets event-card__markets--grid">
                    <div className="market-grid">
                      {event.markets.map((market: Market) => {
                        const marketExpanded = Boolean(expandedMarkets[market.market_id]);
                        const marketCollapsed = Boolean(collapsedMarkets[market.market_id]);
                        const bodyId = `market-card-body-${market.market_id}`;
                        const description = market.description?.trim() ?? "";
                        const descriptionLine = primaryLine(description);
                        const hasMore = description.length > 0 && descriptionLine !== description;
                        const polymarketMarketUrl = market.slug
                          ? `https://polymarket.com/event/${market.slug}`
                          : null;

                        return (
                          <div
                            key={market.market_id}
                            className={`market-card${marketCollapsed ? " market-card--collapsed" : ""}`}
                            data-collapsed={marketCollapsed ? "true" : "false"}
                          >
                          <header className="market-card__header">
                            <div className="market-card__title-row">
                              <h4 className="market-card__title">
                                {polymarketMarketUrl ? (
                                  <a href={polymarketMarketUrl} target="_blank" rel="noopener noreferrer">
                                    {market.question}
                                  </a>
                                ) : (
                                  market.question
                                )}
                              </h4>
                              <button
                                type="button"
                                className="market-card__toggle"
                                aria-expanded={!marketCollapsed}
                                aria-controls={bodyId}
                                onClick={() =>
                                  setCollapsedMarkets((prev) => ({
                                    ...prev,
                                    [market.market_id]: !marketCollapsed,
                                  }))
                                }
                              >
                                {marketCollapsed ? "Show details" : "Hide details"}
                              </button>
                            </div>
                            <div className="market-card__tags">
                              {market.category && <span className="badge">{market.category}</span>}
                              <span className="market-card__sync">Last sync {formatDate(market.last_synced_at)}</span>
                            </div>
                          </header>

                          <div className="market-card__body" id={bodyId} hidden={marketCollapsed}>
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

                            <MarketForecasts results={market.experiment_results} contracts={market.contracts} />
                          </div>
                        </div>
                      );
                    })}
                    </div>
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
