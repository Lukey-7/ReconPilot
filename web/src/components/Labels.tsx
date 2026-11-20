/**
 * Status, cause, check and release labels. Each carries the vocabulary's word; colour only
 * reinforces it. Case statuses are Paper status pills (a dot and the word): Pending amber,
 * Approved and Cleared green, Rejected red, Reclassified info blue.
 */
import type { ReactNode } from "react";

import type { Release } from "../api/types";
import {
  RELEASE_LABELS,
  type CaseStatus,
  causeLabel,
  checkLabel,
  isStatus,
  statusLabel,
} from "../vocabulary";
import { Icon, type IconName } from "./Icon";

/** The status pill kinds in components.css (`.status.late` and so on). */
export type StatusKind = "late" | "wait" | "done" | "info" | "neutral";

const STATUS_KINDS: Record<CaseStatus, StatusKind> = {
  PENDING: "wait",
  APPROVED: "done",
  REJECTED: "late",
  RECLASSIFIED: "info",
  CLEARED: "done",
};

/** A status pill: the dot and the word, coloured by kind. */
export function StatusPill({ kind, children, className = "" }: { kind: StatusKind; children: ReactNode; className?: string }) {
  return <span className={`status ${kind} ${className}`.trim()}>{children}</span>;
}

export function StatusLabel({ status }: { status: string }) {
  const known: CaseStatus = isStatus(status) ? status : "PENDING";
  return (
    <span className={`status ${STATUS_KINDS[known]}`} data-status={known}>
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

/**
 * The day's one release status: Ready to sign off, Blocked, or Signed off. `changed` marks
 * a status that has just moved (Blocked to Ready, say), which pulses once unless motion is
 * reduced; give the badge a new key each time so the pulse replays.
 */
export function ReleaseBadge({ state, changed = false }: { state: ReleaseState; changed?: boolean }) {
  return (
    <span className={`release-badge release-${state}${changed ? " release-changed" : ""}`} data-release={state}>
      <Icon name={RELEASE_ICONS[state]} />
      {RELEASE_LABELS[state]}
    </span>
  );
}
