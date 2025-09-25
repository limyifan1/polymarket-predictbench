const TZ_PATTERN = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;
const DEFAULT_LOCALE = "en-US-u-hc-h23";

function normalizeFractional(value: string): string {
  return value.replace(/(\.\d{3})\d+/, "$1");
}

export function parseDate(
  value: string | Date | null | undefined,
): Date | null {
  if (!value) {
    return null;
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  let normalized = trimmed.includes("T") ? trimmed : trimmed.replace(" ", "T");
  if (!TZ_PATTERN.test(normalized)) {
    normalized = `${normalized}Z`;
  }

  normalized = normalizeFractional(normalized);

  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  return parsed;
}

export function formatDateTime(
  value: string | Date | null | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  const date = parseDate(value);
  if (!date) {
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    return "-";
  }

  const formatOptions = options ? { ...options } : undefined;
  return new Intl.DateTimeFormat(DEFAULT_LOCALE, formatOptions).format(date);
}
