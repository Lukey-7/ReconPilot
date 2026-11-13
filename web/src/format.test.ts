import { describe, expect, it } from "vitest";

import { MISSING, bp, count, dayLabel, dayShort, money, perShare, plural, signedPercent } from "./format";

const MINUS = "−";

describe("format", () => {
  it("groups money with two decimals and a true minus sign", () => {
    expect(money(251234567.891)).toBe("251,234,567.89");
    expect(money(-1234.5)).toBe(`${MINUS}1,234.50`);
    expect(money(1234.5, { signed: true })).toBe("+1,234.50");
    expect(money(-0.001)).toBe("0.00");
    expect(money(null)).toBe(MISSING);
    expect(money(Number.NaN)).toBe(MISSING);
  });

  it("formats NAV per share to six decimals", () => {
    expect(perShare(102.3456781)).toBe("102.345678");
  });

  it("always signs basis points and percentages", () => {
    expect(bp(0.6612)).toBe("+0.66 bp");
    expect(bp(-1.2)).toBe(`${MINUS}1.20 bp`);
    expect(bp(0)).toBe("0.00 bp");
    expect(signedPercent(0.000446)).toBe("+0.045%");
    expect(signedPercent(-0.0123)).toBe(`${MINUS}1.230%`);
  });

  it("counts and pluralises", () => {
    expect(count(12345)).toBe("12,345");
    expect(plural(1, "case")).toBe("1 case");
    expect(plural(3, "case")).toBe("3 cases");
  });

  it("writes business days in British form", () => {
    expect(dayLabel("2026-11-13")).toBe("Fri 13 Nov 2026");
    expect(dayShort("2026-11-09")).toBe("9 Nov");
    expect(dayLabel(null)).toBe(MISSING);
  });
});
