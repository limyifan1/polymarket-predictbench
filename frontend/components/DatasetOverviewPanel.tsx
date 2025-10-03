import { formatDateTime } from "@/lib/date";
import type { DatasetOverview, ExperimentVariantSummary, PipelineRunSummary } from "@/types/market";

type DatasetOverviewPanelProps = {
  overview: DatasetOverview;
};

function formatNumber(value: number): string {
  return value.toLocaleString();
}

function formatPercentage(part: number, total: number): string {
  if (!total || total <= 0) {
    return "-";
  }
  const ratio = (part / total) * 100;
  return `${ratio.toFixed(ratio < 10 ? 1 : 0)}%`;
}

function computeCoverage(part: number, total: number): { percent: number; label: string } {
  if (!total || total <= 0) {
    return { percent: 0, label: "0%" };
  }
  const ratio = (part / total) * 100;
  const rounded = Number.parseFloat(ratio.toFixed(1));
  return { percent: Math.min(100, rounded), label: `${rounded.toFixed(1)}%` };
}

function pickTopVariants(variants: ExperimentVariantSummary[], limit = 6): ExperimentVariantSummary[] {
  return [...variants].sort((a, b) => b.output_count - a.output_count).slice(0, limit);
}

function formatRunStatus(run: PipelineRunSummary): string {
  if (!run.environment) {
    return run.status;
  }
  return `${run.status} · ${run.environment}`;
}

function formatWindowDays(days: number): string {
  return `${days}d`;
}

export function DatasetOverviewPanel({ overview }: DatasetOverviewPanelProps) {
  const researchCoverage = computeCoverage(overview.events_with_research, overview.total_events);
  const forecastCoverage = computeCoverage(overview.events_with_forecasts, overview.total_events);
  const marketCoverage = computeCoverage(overview.markets_with_forecasts, overview.total_markets);
  const totalStatus = overview.market_status.reduce((sum, item) => sum + item.count, 0);

  const topResearchVariants = pickTopVariants(overview.research_variants);
  const topForecastVariants = pickTopVariants(overview.forecast_variants);
  const pipelineRuns = overview.recent_pipeline_runs;
  const hasPipelineRuns = pipelineRuns.length > 0;

  return (
    <section className="overview" aria-labelledby="dataset-overview-heading">
      <h2 id="dataset-overview-heading" className="overview__title">
        Dataset Overview
      </h2>
      <div className="overview__meta">
        <div className="overview__meta-block">
          <span className="overview__meta-label">Snapshot generated</span>
          <span className="overview__meta-value">{formatDateTime(overview.generated_at)}</span>
        </div>
        <div className="overview__meta-block">
          <span className="overview__meta-label">Latest pipeline run</span>
          {overview.latest_pipeline_run ? (
            <div className="overview__meta-run">
              <span className="overview__meta-value">
                {overview.latest_pipeline_run.run_id} · {overview.latest_pipeline_run.status}
              </span>
              <span className="overview__meta-hint">
                Target {formatDateTime(overview.latest_pipeline_run.target_date)} · Window {overview.latest_pipeline_run.window_days}d
              </span>
            </div>
          ) : (
            <span className="overview__meta-hint">No recorded pipeline runs.</span>
          )}
        </div>
      </div>

      <div className="overview__metrics">
        <article className="overview-card" aria-label="Events tracked">
          <h3 className="overview-card__label">Events tracked</h3>
          <p className="overview-card__value">{formatNumber(overview.total_events)}</p>
          <p className="overview-card__hint">
            Research coverage {researchCoverage.label}, forecasts {forecastCoverage.label}
          </p>
        </article>
        <article className="overview-card" aria-label="Research outputs">
          <h3 className="overview-card__label">Research artifacts</h3>
          <p className="overview-card__value">{formatNumber(overview.total_research_artifacts)}</p>
          <p className="overview-card__hint">
            {formatNumber(overview.events_with_research)} events with research
          </p>
        </article>
        <article className="overview-card" aria-label="Forecast outputs">
          <h3 className="overview-card__label">Forecast results</h3>
          <p className="overview-card__value">{formatNumber(overview.total_forecast_results)}</p>
          <p className="overview-card__hint">
            {formatNumber(overview.markets_with_forecasts)} markets with forecasts
          </p>
        </article>
      </div>

      <div className="overview__grid">
        <section className="overview-panel" aria-label="Market status breakdown">
          <header className="overview-panel__header">
            <h3 className="overview-panel__title">Market coverage</h3>
            <span className="overview-panel__hint">
              {formatNumber(overview.total_markets)} markets · coverage {marketCoverage.label}
            </span>
          </header>
          <ul className="overview-status-list">
            {overview.market_status.map((item) => {
              const percent = totalStatus > 0 ? (item.count / totalStatus) * 100 : 0;
              return (
                <li key={item.status} className="overview-status-list__item">
                  <div className="overview-status-list__row">
                    <span className="overview-status-list__label">{item.status}</span>
                    <span className="overview-status-list__value">{formatNumber(item.count)}</span>
                    <span className="overview-status-list__percentage">{formatPercentage(item.count, totalStatus)}</span>
                  </div>
                  <div className="overview-meter" role="presentation">
                    <div className="overview-meter__fill" style={{ width: `${percent.toFixed(1)}%` }} />
                  </div>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="overview-panel" aria-label="Pipeline activity">
          <header className="overview-panel__header">
            <h3 className="overview-panel__title">Pipeline activity</h3>
            <span className="overview-panel__hint">Research and forecast coverage across events</span>
          </header>
          <div className="overview-coverage">
            <div className="overview-coverage__item">
              <div className="overview-coverage__label">Research coverage</div>
              <div className="overview-coverage__value">{researchCoverage.label}</div>
              <div className="overview-meter" role="presentation">
                <div className="overview-meter__fill" style={{ width: `${researchCoverage.percent}%` }} />
              </div>
              <p className="overview-coverage__hint">
                {formatNumber(overview.events_with_research)} of {formatNumber(overview.total_events)} events
              </p>
            </div>
            <div className="overview-coverage__item">
              <div className="overview-coverage__label">Forecast coverage</div>
              <div className="overview-coverage__value">{forecastCoverage.label}</div>
              <div className="overview-meter" role="presentation">
                <div className="overview-meter__fill" style={{ width: `${forecastCoverage.percent}%` }} />
              </div>
              <p className="overview-coverage__hint">
                {formatNumber(overview.events_with_forecasts)} of {formatNumber(overview.total_events)} events
              </p>
            </div>
          </div>
        </section>
      </div>

      <div className="overview__grid overview__grid--full">
        <section className="overview-panel" aria-label="Pipeline run history">
          <header className="overview-panel__header">
            <h3 className="overview-panel__title">Pipeline history</h3>
            <span className="overview-panel__hint">
              {hasPipelineRuns ? `Showing ${pipelineRuns.length} most recent runs` : "No runs recorded"}
            </span>
          </header>
          {hasPipelineRuns ? (
            <table className="overview-table overview-table--compact">
              <thead>
                <tr>
                  <th scope="col">Run ID</th>
                  <th scope="col">Run date</th>
                  <th scope="col">Target date</th>
                  <th scope="col">Window</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {pipelineRuns.map((run) => (
                  <tr key={run.run_id}>
                    <td>
                      <div className="overview-table__primary">{run.run_id}</div>
                    </td>
                    <td className="overview-table__secondary">{formatDateTime(run.run_date)}</td>
                    <td className="overview-table__secondary">{formatDateTime(run.target_date)}</td>
                    <td className="overview-table__numeric">{formatWindowDays(run.window_days)}</td>
                    <td className="overview-table__secondary">{formatRunStatus(run)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="overview-panel__empty">No pipeline history available yet.</p>
          )}
        </section>
      </div>

      <div className="overview__grid">
        <section className="overview-panel" aria-label="Research experiment variants">
          <header className="overview-panel__header">
            <h3 className="overview-panel__title">Research variants</h3>
            <span className="overview-panel__hint">
              Showing top {topResearchVariants.length} of {overview.research_variants.length}
            </span>
          </header>
          {topResearchVariants.length > 0 ? (
            <table className="overview-table">
              <thead>
                <tr>
                  <th scope="col">Experiment variant</th>
                  <th scope="col">Artifacts</th>
                  <th scope="col">Last artifact</th>
                </tr>
              </thead>
              <tbody>
                {topResearchVariants.map((variant) => (
                  <tr key={`${variant.experiment_name}:${variant.variant_name}:${variant.variant_version}`}>
                    <td>
                      <div className="overview-table__primary">{variant.experiment_name}</div>
                      <div className="overview-table__secondary">
                        {variant.variant_name} · v{variant.variant_version}
                      </div>
                    </td>
                    <td className="overview-table__numeric">{formatNumber(variant.output_count)}</td>
                    <td className="overview-table__secondary">{formatDateTime(variant.last_activity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="overview-panel__empty">No research artifacts captured yet.</p>
          )}
        </section>

        <section className="overview-panel" aria-label="Forecast experiment variants">
          <header className="overview-panel__header">
            <h3 className="overview-panel__title">Forecast variants</h3>
            <span className="overview-panel__hint">
              Showing top {topForecastVariants.length} of {overview.forecast_variants.length}
            </span>
          </header>
          {topForecastVariants.length > 0 ? (
            <table className="overview-table">
              <thead>
                <tr>
                  <th scope="col">Experiment variant</th>
                  <th scope="col">Results</th>
                  <th scope="col">Last result</th>
                </tr>
              </thead>
              <tbody>
                {topForecastVariants.map((variant) => (
                  <tr key={`${variant.experiment_name}:${variant.variant_name}:${variant.variant_version}`}>
                    <td>
                      <div className="overview-table__primary">{variant.experiment_name}</div>
                      <div className="overview-table__secondary">
                        {variant.variant_name} · v{variant.variant_version}
                      </div>
                    </td>
                    <td className="overview-table__numeric">{formatNumber(variant.output_count)}</td>
                    <td className="overview-table__secondary">{formatDateTime(variant.last_activity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="overview-panel__empty">No forecast results captured yet.</p>
          )}
        </section>
      </div>
    </section>
  );
}
