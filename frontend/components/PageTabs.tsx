import Link from "next/link";

type PageTabsProps = {
  view: "explorer" | "overview";
  dataset: "local" | "production";
  searchParams: Record<string, string | string[] | undefined>;
};

function buildSearchParams(
  params: Record<string, string | string[] | undefined>,
): URLSearchParams {
  const result = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || key === "") {
      continue;
    }
    if (Array.isArray(value)) {
      for (const entry of value) {
        result.append(key, entry);
      }
    } else {
      result.set(key, value);
    }
  }
  return result;
}

export function PageTabs({ view, dataset, searchParams }: PageTabsProps) {
  const baseParams = buildSearchParams(searchParams);

  const explorerParams = new URLSearchParams(baseParams);
  explorerParams.delete("view");

  const overviewParams = new URLSearchParams(baseParams);
  overviewParams.set("view", "overview");

  const explorerHref = explorerParams.size ? `?${explorerParams.toString()}` : "/";
  const overviewHref = overviewParams.size ? `?${overviewParams.toString()}` : "/?view=overview";

  const localDatasetParams = new URLSearchParams(baseParams);
  localDatasetParams.set("dataset", "local");
  if (view === "explorer") {
    localDatasetParams.delete("view");
  } else {
    localDatasetParams.set("view", "overview");
  }
  const productionDatasetParams = new URLSearchParams(baseParams);
  productionDatasetParams.set("dataset", "production");
  if (view === "explorer") {
    productionDatasetParams.delete("view");
  } else {
    productionDatasetParams.set("view", "overview");
  }

  const localDatasetHref = localDatasetParams.size ? `?${localDatasetParams.toString()}` : "/";
  const productionDatasetHref =
    productionDatasetParams.size ? `?${productionDatasetParams.toString()}` : "/?dataset=production";

  return (
    <div className="page-tabs" aria-label="Dataset views">
      <nav className="page-tabs__nav" aria-label="Primary views">
        <Link
          href={explorerHref}
          className={`page-tabs__item${view === "explorer" ? " is-active" : ""}`}
          scroll={false}
        >
          Explorer
        </Link>
        <Link
          href={overviewHref}
          className={`page-tabs__item${view === "overview" ? " is-active" : ""}`}
          scroll={false}
        >
          Overview
        </Link>
      </nav>
      <div className="page-tabs__aside" aria-label="Dataset selector">
        <span className="page-tabs__aside-label">Dataset</span>
        <Link
          href={localDatasetHref}
          scroll={false}
          className={`page-tabs__pill${dataset === "local" ? " is-active" : ""}`}
        >
          Local
        </Link>
        <Link
          href={productionDatasetHref}
          scroll={false}
          className={`page-tabs__pill${dataset === "production" ? " is-active" : ""}`}
        >
          Production
        </Link>
      </div>
    </div>
  );
}
