/**
 * Response types for every API route the front end calls. Field names are the API's own
 * (snake_case); causes and statuses are the engine's enum values, worded by vocabulary.ts.
 */

export type RoleName = "analyst" | "approver" | "viewer";

export interface User {
  username: string;
  display_name: string;
  role: RoleName;
  is_admin: boolean;
}

export interface LoginResponse {
  user: User;
}

export interface FundSummary {
  code: string;
  name: string;
  base_currency: string;
  start_date: string;
  latest_day: string | null;
  latest_status: string | null;
}

/** `GET /api/funds/{code}`: the fund with its settings and business calendar. */
export interface FundDetail extends FundSummary {
  non_business_dates: string[];
  settings: {
    materiality_bp: number;
    escalate_after_days: number;
    sla_days_material: number;
    sla_days_other: number;
    ai_enabled: boolean;
    /** The fund's own overrides of the release checks' settings (empty: the engine's defaults). */
    check_settings: Record<string, unknown>;
  };
  /** The release checks' settings the engine applies for this fund: its defaults with the fund's overrides. */
  checks_in_force: {
    max_price_age_days: number;
    movement_threshold: number;
    cash_tolerance: number;
    price_move_limits: Record<string, number>;
  };
}

/** `GET` / `PUT /api/auth/me/preferences`: the fund the user last chose to work. */
export interface Preferences {
  fund: string | null;
}

/** One file the engine reads for a day. */
export interface ExpectedFile {
  kind: string;
  filename: string;
  required: boolean;
}

/** Why a day cannot take files now. `day` is the date the reason is about; `day_status` that day's status. */
export interface IntakeBlock {
  /** UPLOADS_OFF, BEFORE_START, NOT_BUSINESS_DAY, PREVIOUS_NOT_LOADED, PREVIOUS_NOT_SIGNED_OFF, SIGNED_OFF or RUNNING. */
  code: string;
  message: string;
  day: string | null;
  day_status: string | null;
}

/** `GET /api/funds/{code}/days/{as_of}/intake`: whether the day can take files now, and which it expects. */
export interface Intake {
  fund: string;
  as_of: string;
  open: boolean;
  blocked: IntakeBlock | null;
  day_status: string | null;
  previous_business_day: string | null;
  previous_status: string | null;
  /** The business day after this one: what opens once this day is signed off. */
  following_day: string;
  expected_files: ExpectedFile[];
  max_file_bytes: number;
  max_rows: number;
}

/** One run of a day, as `GET /api/funds/{code}/days/{as_of}/runs` lists it (newest first). */
export interface DayRun {
  job_id: number;
  status: string;
  attempts: number;
  max_attempts: number;
  started_by: string | null;
  rerun: boolean;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  error: string | null;
  outcome: {
    open_cases: number | null;
    new_cases: number | null;
    carried_cases: number | null;
    cleared_today: number;
    breaks: number | null;
    matches: number | null;
    decisions_reapplied: number;
    decisions_voided: number;
    cases_withdrawn: number;
  } | null;
  skipped: string | null;
}

export interface DayRuns {
  fund: string;
  as_of: string;
  runs: DayRun[];
}

export interface DayListItem {
  as_of: string;
  status: string;
  nav_per_share: number | null;
  open_cases: number | null;
  run_at: string | null;
  signed_off_by: string | null;
  signed_off_at: string | null;
}

/** `GET /api/funds/{code}/days`: newest first. */
export interface DaysList {
  fund: string;
  start_date: string;
  latest_day: string | null;
  next_day: string | null;
  days: DayListItem[];
}

export interface Check {
  name: string;
  status: "PASS" | "WARN" | "FAIL" | string;
  detail: string;
}

export interface Reason {
  code: string;
  message: string;
  case_ids: string[];
}

export interface Release {
  ready: boolean;
  reasons: Reason[];
}

export interface NavDetail {
  gross_assets: number;
  cash: number;
  liabilities: number;
  nav: number;
  nav_per_share: number;
  prior_nav_per_share: number;
  movement: number;
}

export interface DayFile {
  kind: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  uploaded_by: string | null;
  uploaded_at: string | null;
}

export interface Job {
  id: number;
  kind: string;
  status: string;
  attempts: number;
  max_attempts: number;
  error: string | null;
  result: Record<string, unknown> | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/** One problem found in an uploaded file; `row` counts the header as row 1, null for the whole file. */
export interface ValidationIssue {
  file: string;
  row: number | null;
  message: string;
}

export interface ValidationReport {
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

/** `POST /api/funds/{code}/days/{as_of}/files`: the day's status and the whole set's validation. */
export interface UploadResult extends ValidationReport {
  status: string;
}

/** `POST /api/funds/{code}/days/{as_of}/run` (202). */
export interface RunStarted {
  job_id: number;
}

/** `GET /api/funds/{code}/days/{as_of}`. */
export interface Day {
  fund: string;
  as_of: string;
  status: string;
  previous_business_day: string | null;
  files: DayFile[];
  validation: ValidationReport | null;
  error: string | null;
  run_by: string | null;
  run_at: string | null;
  signed_off_by: string | null;
  signed_off_at: string | null;
  nav: {
    nav: number;
    nav_per_share: number;
    prior_nav_per_share: number;
    detail: NavDetail | null;
  } | null;
  checks: Check[] | null;
  release: Release | null;
  summary: Record<string, unknown> | null;
  job: Job | null;
}

/** `GET /api/funds/{code}/days/{as_of}/release?for_user=me`. */
export interface ReleaseForMe extends Release {
  fund: string;
  as_of: string;
  day_status: string | null;
  signed_off: boolean;
  checks: Check[];
  signable_by_me: boolean;
  blocking_for_me: Reason[];
}

/** One row of the case queue (`GET .../cases`). */
export interface QueueCase {
  case_id: string;
  security_id: string;
  security_name: string;
  category: string;
  ai_category: string | null;
  ai_flag: string;
  status: string;
  final_category: string | null;
  nav_impact: number;
  nav_impact_bp: number;
  gross_exposure: number;
  material: boolean;
  escalated: boolean;
  sla_breached: boolean;
  age_days: number;
  age_bucket: string;
  version: number | null;
}

/** A case as the overview lists it: the queue row plus who decided it and its lifecycle. */
export interface OverviewCase extends QueueCase {
  reviewed_by: string;
  reviewed_role: string;
  review_note: string;
  first_seen: string;
  sla_days: number;
  /** Recorded when the case was escalated: label it "at escalation", not today's impact. */
  escalation_reason: string;
}

export interface ClearedCase {
  case_id: string;
  security_id: string;
  security_name: string;
  category: string;
  final_category: string | null;
  resolved_category: string | null;
  status: string;
  clear_reason: string;
  nav_impact: number;
  age_days: number;
  first_seen: string;
  cleared_on: string;
}

export interface TrendDay {
  as_of: string;
  open_cases: number;
  new_cases: number;
  cleared_cases: number;
  material_open: number;
  escalated_open: number;
  sla_breaches_open: number;
  aged_over_5: number;
  /** Net NAV impact of the cases open at the end of the day. */
  open_nav_impact: number;
  /** Gross: their absolute impacts added up, so offsetting breaks cannot hide. */
  open_gross_impact: number;
  avg_days_to_resolve: number | null;
}

export interface AgeingBucket {
  bucket: string;
  count: number;
  net: number;
  gross: number;
}

/** `GET /api/funds/{code}/days/{as_of}/overview`. */
export interface Overview {
  fund: { code: string; name: string; base_currency: string; materiality_bp: number };
  as_of: string;
  day_status: string;
  has_run: boolean;
  run_at: string | null;
  run_by: string | null;
  signed_off_by: string | null;
  signed_off_at: string | null;
  nav: {
    nav: number;
    nav_per_share: number;
    prior_nav_per_share: number;
    movement: number | null;
    gross_assets: number | null;
    cash: number | null;
    liabilities: number | null;
  } | null;
  checks: Check[];
  release: Release;
  run: { matches: number; breaks: number; new_cases: number; carried_cases: number } | null;
  accounted: {
    breaks_found: number;
    breaks_in_cases: number;
    breaks_not_in_case: number;
    open_cases: number;
    decided: number;
    approved: number;
    rejected: number;
    reclassified: number;
    pending: number;
  } | null;
  impact: {
    cases: OverviewCase[];
    net: number;
    gross: number;
    gross_exposure: number;
    material: number;
  } | null;
  ageing: AgeingBucket[];
  sla_breaches: OverviewCase[];
  escalations: OverviewCase[];
  cleared_today: ClearedCase[];
  trend: TrendDay[];
}

/** The engine's full case (`reconpilot.models.Case`), as `case` in a case's detail. */
export interface EngineCase {
  case_id: string;
  security_id: string;
  category: string;
  confidence: number;
  explanation: string;
  query_draft: string;
  break_ids: string[];
  status: string;
  final_category: string | null;
  reviewed_by: string;
  review_note: string;
  ai_category: string | null;
  ai_confidence: number | null;
  ai_explanation: string;
  ai_steps: string[];
  ai_query: string;
  ai_model: string;
  /** "" (no AI for this case), "ACCEPTED" (passed the guardrails) or "FALLBACK" (the rules stand). */
  ai_status: string;
  ai_flag: string;
  ai_fallback_reason: string;
  nav_impact: number;
  nav_impact_bp: number;
  gross_exposure: number;
  material: boolean;
  break_kinds: string[];
  first_seen: string;
  age_days: number;
  age_bucket: string;
  escalated: boolean;
  /** Recorded when the case was escalated: label it "at escalation", not today's impact. */
  escalation_reason: string;
  sla_days: number;
  sla_breached: boolean;
  cleared_on: string;
  clear_reason: string;
  resolved_category: string | null;
  reviewed_role: string;
}

export interface CaseBreak {
  break_id: string;
  kind: string;
  security_id: string;
  book_value: number | null;
  custodian_value: number | null;
  difference: number;
  reference: string;
  note: string;
}

export interface SecurityRecord {
  security_id: string;
  name: string;
  currency: string;
  asset_class: string;
}

export interface BookPosition {
  security_id: string;
  quantity: number;
  price: number;
  price_date: string;
  currency: string;
}

export interface CustodianHolding {
  security_id: string;
  quantity: number;
  price: number;
  currency: string;
}

export interface BookTrade {
  trade_id: string;
  trade_date: string;
  settle_date: string;
  security_id: string;
  side: string;
  quantity: number;
  price: number;
  currency: string;
  fx_rate: number;
  fees: number;
}

export interface BookCashEntry {
  reference: string;
  value_date: string;
  security_id: string;
  description: string;
  amount: number;
}

export interface CustodianCashLine {
  entry_id: string;
  value_date: string;
  security_id: string;
  reference: string;
  description: string;
  amount: number;
}

/** An item carried from the previous day: a book item or a custodian cash line. */
export interface CarriedItem {
  side: string;
  reference?: string;
  security_id?: string;
  amount?: number;
  origin_date?: string;
  value_date?: string;
  description?: string;
  entry_id?: string;
}

/** One entry in a case's history: an audit-log entry or a recorded decision, oldest first. */
export type CaseHistoryEntry =
  | {
      type: "audit";
      at: string;
      seq: number;
      actor: string;
      role: string;
      action: string;
      payload: Record<string, unknown>;
    }
  | {
      type: "decision";
      at: string;
      decision_id: number;
      user: string | null;
      role: string;
      decision: string;
      category: string | null;
      final_category: string | null;
      note: string;
      case_version: number;
      voided_at: string | null;
      void_reason: string | null;
    };

/** `GET /api/funds/{code}/cases/{case_id}?as_of=`: the case as it stood that day, with its evidence. */
export interface CaseDetail extends QueueCase {
  as_of: string;
  day_status: string;
  is_open: boolean;
  case: EngineCase;
  security: SecurityRecord | null;
  breaks: CaseBreak[];
  book_position: BookPosition | null;
  custodian_holding: CustodianHolding | null;
  book_trades: BookTrade[];
  book_cash: BookCashEntry[];
  custodian_cash: CustodianCashLine[];
  carried_items: CarriedItem[];
  fx_rate: number | null;
  history: CaseHistoryEntry[];
  /** The case at the end of every day it was in a run, oldest first. */
  days: CaseDay[];
}

/** A case as it stood at the end of one day it was in a run (its ledger snapshot). */
export interface CaseDay {
  as_of: string;
  day_status: string;
  /** False on the day the case cleared. */
  is_open: boolean;
  status: string;
  /** The cause a person read off the case that day (resolved, reclassified, accepted AI, else the rules'). */
  cause: string;
  /** The rules' cause. */
  category: string;
  age_days: number;
  nav_impact: number;
  nav_impact_bp: number;
  material: boolean;
  escalated: boolean;
  sla_breached: boolean;
  reviewed_by: string | null;
}

/** `POST /api/funds/{code}/cases/{case_id}/decision`. */
export interface DecisionRequest {
  decision: "approve" | "reject" | "reclassify";
  category?: string;
  note: string;
  version: number;
}

/** One entry of the hash-chained audit log, as the day's audit trail lists it. */
export interface AuditEntry {
  seq: number;
  ts: string;
  actor: string;
  role: string;
  action: string;
  case_id: string | null;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

/** `GET /api/funds/{code}/days/{as_of}/audit`: the day's entries, oldest first, and the whole chain re-checked. */
export interface DayAudit {
  fund: string;
  as_of: string;
  entries: AuditEntry[];
  chain_ok: boolean;
  /** The first entry that does not fit the chain, when it is broken. */
  broken_at: number | null;
}

/** Counts and impact of a set of open cases: net, and gross (absolute impacts added up). */
export interface MiFigures {
  count: number;
  net: number;
  gross: number;
}

export interface MiBucketCell extends MiFigures {
  bucket: string;
}

/** A cause's (or the total's) open cases, overall and per age bucket. */
export interface MiBlock extends MiFigures {
  cells: MiBucketCell[];
}

export interface MiCauseRow extends MiBlock {
  cause: string;
}

/** One of the open cases with the largest absolute NAV impact. */
export interface MiTopCase {
  case_id: string;
  security_id: string;
  security_name: string;
  /** The cause a person reads off the case now (resolved, reclassified, accepted AI, else the rules'). */
  cause: string;
  nav_impact: number;
  nav_impact_bp: number;
  age_days: number;
  material: boolean;
  escalated: boolean;
  sla_breached: boolean;
  status: string;
}

/** A case that went past its SLA up to the day; `cleared_on` once it has since cleared. */
export interface MiSlaCase {
  case_id: string;
  security_id: string;
  security_name: string;
  cause: string;
  age_days: number;
  sla_days: number;
  material: boolean;
  status: string;
  cleared_on: string | null;
}

export interface MiTrendDay extends TrendDay {
  open_gross_impact: number;
}

/** `GET /api/funds/{code}/days/{as_of}/mi`. */
export interface Mi {
  fund: { code: string; name: string; base_currency: string; materiality_bp: number };
  as_of: string;
  day_status: string;
  has_run: boolean;
  run_days: number;
  by_cause_age: { buckets: string[]; rows: MiCauseRow[]; total: MiBlock };
  time_to_resolve: {
    rows: { cause: string; cleared: number; avg_days: number | null }[];
    all: { cleared: number; avg_days: number | null };
  };
  top_open: MiTopCase[];
  sla_breaches: MiSlaCase[];
  trend: MiTrendDay[];
  exports: { report: string; mi_csv: string } | null;
}

/** One entry of the whole audit log, with the code of the fund it concerns (null for system entries). */
export interface AuditLogEntry extends AuditEntry {
  fund: string | null;
}

/** `GET /api/audit`: one page of matching entries, newest first. */
export interface AuditPage {
  entries: AuditLogEntry[];
  /** Every matching entry. */
  total: number;
  /** How many matching entries sit above this page. */
  newer: number;
  has_newer: boolean;
  /** The cursor for the next newer page; null when that page is the first. */
  newer_before: number | null;
  /** The cursor for the next older page; null on the last page. */
  next_before: number | null;
  /** The newest entry in the whole log. */
  latest_seq: number;
}

/** `GET /api/audit/facets`: the actors and actions present, for the filter menus. */
export interface AuditFacets {
  actors: string[];
  actions: string[];
}

/** `GET /api/audit/entries/{seq}`: one entry with the server's check of it. */
export interface AuditEntryCheck extends AuditLogEntry {
  /** Its hash recomputes from its fields. */
  hash_ok: boolean;
  /** Its previous hash is the hash of the entry before it. */
  linked: boolean;
}

/** `POST /api/audit/verify`: the whole chain re-checked on the server. */
export interface ChainCheck {
  chain_ok: boolean;
  broken_at: number | null;
  entries: number;
  last_seq: number | null;
  last_hash: string | null;
  verified_at: string;
  verified_by: string;
  /** The entry recording this check. */
  seq: number;
}

/** The audit log's filters, named as the API names them. Absent means "any". */
export interface AuditFilters {
  fund?: string;
  as_of?: string;
  from?: string;
  to?: string;
  actor?: string;
  action?: string;
  case?: string;
}
