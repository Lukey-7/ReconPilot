/**
 * Number and date formatting (en-GB). Figures are rendered with tabular numerals by CSS;
 * these functions decide grouping, decimals and signs. A missing value renders as an
 * en dash so a gap never reads as zero.
 */

export const MISSING = "–";
const MINUS = "−"; // a true minus sign, the same width as a plus in tabular figures

function fixed(decimals: number): Intl.NumberFormat {
  return new Intl.NumberFormat("en-GB", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function isNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function sign(value: number, signed: boolean, text: string): string {
  // Treat a value that rounds to zero as zero, so "-0.00" never appears.
  const zero = Number(text.replace(/[^0-9.]/g, "")) === 0;
  if (value < 0 && !zero) return `${MINUS}${text}`;
  if (signed && value > 0 && !zero) return `+${text}`;
  return text;
}

/** An amount of money: grouped thousands, two decimals; `signed` adds a plus to positive amounts. */
export function money(value: number | null | undefined, { signed = false, decimals = 2 } = {}): string {
  if (!isNumber(value)) return MISSING;
  return sign(value, signed, fixed(decimals).format(Math.abs(value)));
}

/** A whole count with grouped thousands. */
export function count(value: number | null | undefined): string {
  if (!isNumber(value)) return MISSING;
  return sign(value, false, fixed(0).format(Math.abs(value)));
}

/** NAV per share: six decimals, as the engine computes it. */
export function perShare(value: number | null | undefined): string {
  return money(value, { decimals: 6 });
}

/** Basis points of NAV, always signed: "+0.66 bp". */
export function bp(value: number | null | undefined, decimals = 2): string {
  if (!isNumber(value)) return MISSING;
  return `${sign(value, true, fixed(decimals).format(Math.abs(value)))} bp`;
}

/** A fraction as a signed percentage: 0.00042 -> "+0.042%". */
export function signedPercent(fraction: number | null | undefined, decimals = 3): string {
  if (!isNumber(fraction)) return MISSING;
  return `${sign(fraction, true, fixed(decimals).format(Math.abs(fraction * 100)))}%`;
}

function parseDay(isoDay: string): Date {
  const [y, m, d] = isoDay.split("-").map(Number);
  return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1));
}

/** A business day: "Fri 13 Nov 2026". */
export function dayLabel(isoDay: string | null | undefined): string {
  if (!isoDay) return MISSING;
  const parts = new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).formatToParts(parseDay(isoDay));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return [part("weekday"), part("day"), part("month"), part("year")].join(" ");
}

/** A short business day: "13 Nov". */
export function dayShort(isoDay: string | null | undefined): string {
  if (!isoDay) return MISSING;
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }).format(
    parseDay(isoDay),
  );
}

/** A moment in the user's local time: "13 Nov 2026, 09:41". */
export function timestamp(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return MISSING;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** "1 case", "2 cases". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${count(n)} ${n === 1 ? one : many}`;
}
