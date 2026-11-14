import { describe, expect, it } from "vitest";

import {
  CAUSES,
  CAUSE_LABELS,
  EXPORTS,
  STATUSES,
  STATUS_LABELS,
  STATUS_TONES,
  TREND_MEASURES,
  ageBucketLabel,
  auditActionLabel,
  breakKindLabel,
  caseStatus,
  causeLabel,
  checkLabel,
  dayStatusLabel,
  RELEASE_CONDITIONS,
  RELEASE_REASONS,
  releaseConditionLabel,
  releaseReasonLabel,
  roleLabel,
  statusLabel,
} from "./vocabulary";

describe("vocabulary", () => {
  it("names every engine cause exactly as the design does", () => {
    expect(CAUSES.map((c) => CAUSE_LABELS[c])).toEqual([
      "Missing trade",
      "Late settlement",
      "Price mismatch",
      "Stock split",
      "Dividend",
      "FX difference",
      "Unexplained",
    ]);
    expect(causeLabel("TIMING")).toBe("Late settlement");
    expect(causeLabel("FX_DIFFERENCE")).toBe("FX difference");
  });

  it("never shows a raw code for a cause", () => {
    expect(causeLabel("SOMETHING_NEW")).toBe("Unexplained");
    expect(causeLabel(null)).toBe("Unexplained");
  });

  it("names the statuses, with amber only for Pending", () => {
    expect(STATUSES.map((s) => STATUS_LABELS[s])).toEqual(["Pending", "Approved", "Rejected", "Reclassified", "Cleared"]);
    const amber = Object.entries(STATUS_TONES)
      .filter(([, tone]) => tone === "signal")
      .map(([s]) => s);
    expect(amber).toEqual(["PENDING"]);
    expect(statusLabel("RECLASSIFIED")).toBe("Reclassified");
  });

  it("shows a cleared case as Cleared whatever its decision", () => {
    expect(caseStatus({ status: "APPROVED", cleared_on: "2026-11-10" })).toBe("CLEARED");
    expect(caseStatus({ status: "REJECTED", cleared_on: "" })).toBe("REJECTED");
  });

  it("words release reasons, checks, day statuses, roles and age buckets", () => {
    expect(releaseReasonLabel("FOUR_EYES")).toBe("Four-eyes rule");
    expect(releaseReasonLabel("MATERIAL_NOT_APPROVED")).toBe("Material cases awaiting approval");
    expect(checkLabel("WARN")).toBe("Warning");
    expect(dayStatusLabel("signed_off")).toBe("Signed off");
    expect(dayStatusLabel(null)).toBe("No files yet");
    expect(roleLabel("approver")).toBe("Approver");
    expect(ageBucketLabel(">5")).toBe("Over 5 days");
  });

  it("words break kinds and audit actions, keeping an unknown action's own code", () => {
    expect(breakKindLabel("CASH_MISSING_IN_BOOK")).toBe("Cash not in book");
    expect(auditActionLabel("CASE_AUTO_CLEARED")).toBe("Cleared automatically");
    expect(auditActionLabel("AI_CALL")).toBe("AI second opinion");
    expect(auditActionLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });

  it("words the actions the audit log viewer shows beyond a day's trail", () => {
    expect(auditActionLabel("AUDIT_CHAIN_VERIFIED")).toBe("Chain verified");
    expect(auditActionLabel("USER_CREATED")).toBe("User created");
    expect(auditActionLabel("FUND_CREATED")).toBe("Fund created");
    expect(auditActionLabel("ACCOUNT_LOCKED")).toBe("Account locked");
  });

  it("names a release condition for every release reason", () => {
    expect(Object.keys(RELEASE_CONDITIONS).sort()).toEqual(Object.keys(RELEASE_REASONS).sort());
    expect(releaseConditionLabel("PENDING_DECISIONS")).toBe("Every open case decided");
    expect(releaseConditionLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });

  it("names the exports and the trend's measures", () => {
    expect(auditActionLabel("EXPORT_DOWNLOADED")).toBe("Export downloaded");
    expect(Object.values(EXPORTS)).toEqual(["Exception report", "MI data"]);
    expect(Object.values(TREND_MEASURES)).toEqual(["Open", "New", "Cleared", "Material", "Escalated", "Past SLA"]);
  });
});
