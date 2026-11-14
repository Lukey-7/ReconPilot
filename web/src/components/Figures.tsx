/** Figures: tabular numerals, en-GB grouping, true minus signs. */
import { bp, money, perShare, signedPercent } from "../format";
import { useTween } from "../motion";

export function Money({ value, signed = false, decimals = 2 }: { value: number | null | undefined; signed?: boolean; decimals?: number }) {
  return <span className="fig">{money(value, { signed, decimals })}</span>;
}

/** Money that eases to a new value (another day, a rerun); at once under reduced motion. */
export function TweenedMoney({ value, signed = false }: { value: number | null | undefined; signed?: boolean }) {
  const shown = useTween(value ?? null);
  return <>{money(value == null ? null : shown, { signed })}</>;
}

export function PerShare({ value }: { value: number | null | undefined }) {
  return <span className="fig">{perShare(value)}</span>;
}

export function Bp({ value }: { value: number | null | undefined }) {
  return <span className="fig">{bp(value)}</span>;
}

export function Pct({ value }: { value: number | null | undefined }) {
  return <span className="fig">{signedPercent(value)}</span>;
}
