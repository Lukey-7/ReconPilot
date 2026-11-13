/**
 * The one vocabulary of ReconPilot (spec section 10).
 *
 * The API speaks the engine's enum values (MISSING_TRADE, PENDING, ...). Every word a
 * person reads for a cause, a status, a release reason, a check result, a day status,
 * a role or an age bucket comes from here, so the same thing is called the same name on
 * every screen and in every export.
 */

/** The engine's causes (`reconpilot.models.Category`), in the order screens list them. */
export const CAUSES = [
  "MISSING_TRADE",
  "TIMING",
  "PRICE_MISMATCH",
  "STOCK_SPLIT",
  "DIVIDEND",
  "FX_DIFFERENCE",
  "UNKNOWN",
] as const;
export type Cause = (typeof CAUSES)[number];

export const CAUSE_LABELS: Record<Cause, string> = {
  MISSING_TRADE: "Missing trade",
  TIMING: "Late settlement",
  PRICE_MISMATCH: "Price mismatch",
  STOCK_SPLIT: "Stock split",
  DIVIDEND: "Dividend",
  FX_DIFFERENCE: "FX difference",
  UNKNOWN: "Unexplained",
};

export function isCause(value: unknown): value is Cause {
  return typeof value === "string" && (CAUSES as readonly string[]).includes(value);
}

/** The word for a cause. Anything the engine might add later reads as "Unexplained", never as a code. */
export function causeLabel(cause: string | null | undefined): string {
  return isCause(cause) ? CAUSE_LABELS[cause] : CAUSE_LABELS.UNKNOWN;
}

/** Case statuses: the engine's four decisions, plus Cleared for a case a later day's data matched. */
export const STATUSES = ["PENDING", "APPROVED", "REJECTED", "RECLASSIFIED", "CLEARED"] as const;
export type CaseStatus = (typeof STATUSES)[number];

export const STATUS_LABELS: Record<CaseStatus, string> = {
  PENDING: "Pending",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  RECLASSIFIED: "Reclassified",
  CLEARED: "Cleared",
};

/**
 * How each status looks. `signal` is the "needs you" amber and is used for Pending only;
 * `pos` and `neg` are the restrained green and red, always shown with the icon and word.
 */
export const STATUS_TONES: Record<CaseStatus, "signal" | "pos" | "neg" | "neutral"> = {
  PENDING: "signal",
  APPROVED: "pos",
  REJECTED: "neg",
  RECLASSIFIED: "neutral",
  CLEARED: "pos",
};

export function isStatus(value: unknown): value is CaseStatus {
  return typeof value === "string" && (STATUSES as readonly string[]).includes(value);
}

export function statusLabel(status: string | null | undefined): string {
  return isStatus(status) ? STATUS_LABELS[status] : (status ?? "");
}

/** The status a case shows: Cleared once a later day matched it, otherwise its decision status. */
export function caseStatus(c: { status: string; cleared_on?: string | null }): CaseStatus {
  if (c.cleared_on) return "CLEARED";
  return isStatus(c.status) ? c.status : "PENDING";
}

/** Reasons the server gives for a blocked release (`reconpilot_web.release`). */
export const RELEASE_REASONS = {
  NOT_RUN: "Not run",
  PENDING_DECISIONS: "Pending decisions",
  MATERIAL_NOT_APPROVED: "Material cases awaiting approval",
  ESCALATED_NEEDS_APPROVER: "Escalated cases awaiting an approver",
  CHECK_FAILED: "Failed check",
  FOUR_EYES: "Four-eyes rule",
} as const;
export type ReleaseReasonCode = keyof typeof RELEASE_REASONS;

export function releaseReasonLabel(code: string): string {
  return code in RELEASE_REASONS ? RELEASE_REASONS[code as ReleaseReasonCode] : code;
}

export const RELEASE_LABELS = {
  ready: "Ready to sign off",
  blocked: "Blocked",
  signedOff: "Signed off",
} as const;

/** Release check results (`reconpilot.nav`). */
export const CHECK_RESULTS = {
  PASS: "Pass",
  WARN: "Warning",
  FAIL: "Fail",
} as const;
export type CheckResult = keyof typeof CHECK_RESULTS;

export function checkLabel(status: string): string {
  return status in CHECK_RESULTS ? CHECK_RESULTS[status as CheckResult] : status;
}

/** A business day's status (`business_days.status`). */
export const DAY_STATUSES = {
  uploaded: "Files have errors",
  validated: "Validated, not run",
  running: "Running",
  ready: "Ready for review",
  signed_off: "Signed off",
  failed: "Run failed",
} as const;
export type DayStatus = keyof typeof DAY_STATUSES;

export function dayStatusLabel(status: string | null | undefined): string {
  if (status == null) return "No files yet";
  return status in DAY_STATUSES ? DAY_STATUSES[status as DayStatus] : status;
}

export const ROLES = {
  analyst: "Analyst",
  approver: "Approver",
  viewer: "Viewer",
} as const;
export type Role = keyof typeof ROLES;

export function roleLabel(role: string): string {
  return role in ROLES ? ROLES[role as Role] : role;
}

/** Age buckets in business days open (`reconpilot.ledger.BUCKETS`). */
export const AGE_BUCKETS = {
  "0-1": "0 to 1 day",
  "2-5": "2 to 5 days",
  ">5": "Over 5 days",
} as const;
export type AgeBucket = keyof typeof AGE_BUCKETS;

export function ageBucketLabel(bucket: string): string {
  return bucket in AGE_BUCKETS ? AGE_BUCKETS[bucket as AgeBucket] : bucket;
}

/** Case flags, shown as labelled tags rather than tiny buttons. */
export const FLAGS = {
  material: "Material",
  escalated: "Escalated",
  sla: "Past SLA",
  ai: "AI disagrees",
} as const;

/** Decisions a person can make on a case. */
export const DECISIONS = {
  approve: "Approve",
  reject: "Reject",
  reclassify: "Reclassify",
} as const;
export type DecisionKind = keyof typeof DECISIONS;
