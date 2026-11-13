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

/** `GET /api/funds/{code}/days/{as_of}`. */
export interface Day {
  fund: string;
  as_of: string;
  status: string;
  previous_business_day: string | null;
  files: DayFile[];
  validation: Record<string, unknown> | null;
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
  open_nav_impact: number;
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
