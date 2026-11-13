/**
 * Status, cause, check and release labels. Each pairs an icon with the vocabulary's word;
 * colour only reinforces it. Amber (signal) is reserved for what needs someone.
 */
import type { Release } from "../api/types";
import {
  RELEASE_LABELS,
  STATUS_TONES,
  type CaseStatus,
  causeLabel,
  checkLabel,
  isStatus,
  statusLabel,
} from "../vocabulary";
import { Icon, type IconName } from "./Icon";

const STATUS_ICONS: Record<CaseStatus, IconName> = {
  PENDING: "dot",
  APPROVED: "check",
  REJECTED: "cross",
  RECLASSIFIED: "reclass",
  CLEARED: "ring",
};

export function StatusLabel({ status }: { status: string }) {
  const known: CaseStatus = isStatus(status) ? status : "PENDING";
  return (
    <span className={`pill tone-${STATUS_TONES[known]}`} data-status={known}>
      <Icon name={STATUS_ICONS[known]} />
      {statusLabel(isStatus(status) ? status : known)}
    </span>
  );
}

export function CauseLabel({ cause }: { cause: string | null | undefined }) {
  return <span className="cause">{causeLabel(cause)}</span>;
}

const CHECK_ICONS: Record<string, IconName> = { PASS: "check", WARN: "warn", FAIL: "cross" };
const CHECK_TONES: Record<string, string> = { PASS: "pos", WARN: "neutral", FAIL: "neg" };

export function CheckLabel({ status }: { status: string }) {
  return (
    <span className={`st tone-${CHECK_TONES[status] ?? "neutral"}`} data-check={status}>
      <Icon name={CHECK_ICONS[status] ?? "dot"} />
      {checkLabel(status)}
    </span>
  );
}

export type ReleaseState = "ready" | "blocked" | "signedOff";

export function releaseState(release: Release | null | undefined, signedOff: boolean): ReleaseState {
  if (signedOff) return "signedOff";
  return release?.ready ? "ready" : "blocked";
}

const RELEASE_ICONS: Record<ReleaseState, IconName> = { ready: "check", blocked: "warn", signedOff: "lock" };

/** The day's one release status: Ready to sign off, Blocked, or Signed off. */
export function ReleaseBadge({ state }: { state: ReleaseState }) {
  return (
    <span className={`release-badge release-${state}`} data-release={state}>
      <Icon name={RELEASE_ICONS[state]} />
      {RELEASE_LABELS[state]}
    </span>
  );
}
