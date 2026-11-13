/** Figures: tabular numerals, en-GB grouping, true minus signs. */
import { bp, money, perShare, signedPercent } from "../format";

export function Money({ value, signed = false, decimals = 2 }: { value: number | null | undefined; signed?: boolean; decimals?: number }) {
  return <span className="fig">{money(value, { signed, decimals })}</span>;
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
