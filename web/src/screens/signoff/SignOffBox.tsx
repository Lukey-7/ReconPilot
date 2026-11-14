/**
 * The sign-off action and every state it can be in, each said in plain words:
 *
 * - signed off: locked, by whom and when, and the next business day now open for files;
 * - viewer: read-only; analyst: only an approver signs off;
 * - approver, day not run or conditions unmet: the button stays shut and says why;
 * - approver who decided a case today: four-eyes, another approver must sign off;
 * - approver, ready: "Sign off NAV" asks once more, showing the figures being released.
 *
 * The server decides all of this (`signable_by_me`, `blocking_for_me`) and checks it again
 * when the request arrives; a refusal (409 with reasons) is shown in the server's words.
 */
import * as Dialog from "@radix-ui/react-dialog";
import { useId, useState } from "react";

import { ApiError } from "../../api/client";
import { useSignOff } from "../../api/queries";
import type { Day, FundSummary, Reason, ReleaseForMe, User } from "../../api/types";
import { Icon } from "../../components/Icon";
import { ReleaseBadge, releaseState } from "../../components/Labels";
import { count, dayLabel, money, perShare, signedPercent, timestamp } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { releaseReasonLabel } from "../../vocabulary";
import { CaseIdList } from "./CaseIdList";

type Refusal = { message: string; reasons: Reason[] };

function NextDay({ asOf }: { asOf: string }) {
  const { days, setDay } = useWorkspace();
  if (!days) return null;
  const next = days.next_day;
  const later = days.latest_day && days.latest_day > asOf ? days.latest_day : null;
  if (next && next > asOf) {
    return (
      <div className="so-next">
        <p>
          The next business day, <strong>{dayLabel(next)}</strong>, is open for its files.
        </p>
        <button type="button" className="btn" onClick={() => setDay(next)}>
          Go to {dayLabel(next)}
        </button>
      </div>
    );
  }
  if (later) {
    return (
      <div className="so-next">
        <p>
          A later business day, <strong>{dayLabel(later)}</strong>, is already loaded.
        </p>
        <button type="button" className="btn" onClick={() => setDay(later)}>
          Go to {dayLabel(later)}
        </button>
      </div>
    );
  }
  return null;
}

function ConfirmDialog({
  open,
  onOpenChange,
  fund,
  asOf,
  day,
  openCases,
  busy,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fund: FundSummary;
  asOf: string;
  day: Day | undefined;
  openCases: number | null;
  busy: boolean;
  onConfirm: () => void;
}) {
  const nav = day?.nav ?? null;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content className="dialog so-dialog">
          <div className="dialog-head">
            <Dialog.Title>Sign off the NAV?</Dialog.Title>
          </div>
          <Dialog.Description>
            This releases the NAV of {fund.name} for {dayLabel(asOf)} and locks the day: its files, cases and
            decisions can no longer change. It is written to the audit log under your name.
          </Dialog.Description>
          <dl className="so-figs">
            <div>
              <dt>NAV, {fund.base_currency}</dt>
              <dd className="fig">{money(nav?.nav)}</dd>
            </div>
            <div>
              <dt>NAV per share</dt>
              <dd className="fig">{perShare(nav?.nav_per_share)}</dd>
            </div>
            <div>
              <dt>Movement</dt>
              <dd className="fig">{signedPercent(nav?.detail?.movement)}</dd>
            </div>
            {openCases != null && (
              <div>
                <dt>Open cases, all decided</dt>
                <dd className="fig">{count(openCases)}</dd>
              </div>
            )}
          </dl>
          <div className="so-dialog-actions">
            <Dialog.Close className="btn ghost" disabled={busy}>
              Cancel
            </Dialog.Close>
            <button type="button" className="btn primary" onClick={onConfirm} disabled={busy}>
              <Icon name="lock" />
              {busy ? "Signing off…" : "Sign off NAV"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Why this person cannot sign off now, in plain words, or null when they can. */
export function blockedMessage(release: ReleaseForMe, user: User): { title: string; text: string; reasons: Reason[] } | null {
  if (user.role === "viewer") {
    return {
      title: "Read-only",
      text: "Viewers can follow the release but cannot sign off. An approver who decided none of today's cases signs off the NAV.",
      reasons: [],
    };
  }
  if (user.role !== "approver") {
    return {
      title: "Only an approver can sign off",
      text: "Analysts decide cases. Once every condition is met, an approver who decided none of today's cases signs off the NAV.",
      reasons: [],
    };
  }
  if (release.signable_by_me) return null;
  const notRun = release.reasons.find((r) => r.code === "NOT_RUN");
  if (notRun) return { title: "Not run yet", text: `${notRun.message} Sign-off opens once it has run and every condition is met.`, reasons: [] };
  if (release.reasons.length) {
    const n = new Set(release.reasons.map((r) => r.code)).size;
    return {
      title: "Not ready",
      text: `Sign-off opens once every release condition is met. ${n === 1 ? "One condition is" : `${count(n)} conditions are`} not met yet.`,
      reasons: [],
    };
  }
  const fourEyes = release.blocking_for_me.filter((r) => r.code === "FOUR_EYES");
  if (fourEyes.length) {
    return {
      title: "Four-eyes rule",
      text: "The day is ready, but whoever signs off must have decided none of its open cases.",
      reasons: fourEyes,
    };
  }
  return {
    title: "Not available",
    text: "The server does not allow you to sign off this day.",
    reasons: release.blocking_for_me,
  };
}

export function SignOffBox({
  fund,
  asOf,
  release,
  day,
  openCases,
  user,
}: {
  fund: FundSummary;
  asOf: string;
  release: ReleaseForMe;
  day: Day | undefined;
  openCases: number | null;
  user: User;
}) {
  const [confirming, setConfirming] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [done, setDone] = useState(false);
  const signOff = useSignOff(fund.code, asOf);
  const describedBy = useId();

  const signedOff = release.signed_off || day?.status === "signed_off";
  const state = releaseState(release, signedOff);

  function confirm() {
    setRefusal(null);
    signOff.mutate(undefined, {
      onSuccess: () => {
        setConfirming(false);
        setDone(true);
      },
      onError: (error) => {
        setConfirming(false);
        setRefusal(
          error instanceof ApiError
            ? { message: error.message, reasons: error.reasons }
            : { message: "Sign-off failed. Try again.", reasons: [] },
        );
      },
    });
  }

  let body;
  if (signedOff) {
    body = (
      <>
        <p className="so-msg" aria-live="polite">
          {done ? "Signed off. " : ""}
          The NAV was signed off by <strong>{day?.signed_off_by ?? "an approver"}</strong>
          {day?.signed_off_at ? `, ${timestamp(day.signed_off_at)}` : ""}. The day is locked: its files, cases and
          decisions can no longer change.
        </p>
        <NextDay asOf={asOf} />
      </>
    );
  } else {
    const blocked = blockedMessage(release, user);
    const isApprover = user.role === "approver";
    body = (
      <>
        {blocked ? (
          <div className="so-msg so-blocked" id={describedBy}>
            <p className="so-blocked-title">
              <Icon name="lock" />
              {blocked.title}
            </p>
            <p>{blocked.text}</p>
            {blocked.reasons.map((r, i) => (
              <div key={`${r.code}-${i}`} className="so-cond-reason">
                <p>{r.message}</p>
                <CaseIdList ids={r.case_ids} label="Cases you decided" />
              </div>
            ))}
          </div>
        ) : (
          <p className="so-msg" id={describedBy}>
            Every release condition is met and you decided none of today&rsquo;s open cases. Signing off releases the
            NAV and locks the day.
          </p>
        )}
        {isApprover && (
          <button
            type="button"
            className="btn primary so-sign-btn"
            disabled={!!blocked || signOff.isPending}
            aria-describedby={describedBy}
            onClick={() => {
              setRefusal(null);
              setConfirming(true);
            }}
          >
            <Icon name="lock" />
            Sign off NAV
          </button>
        )}
        {refusal && (
          <div className="so-refusal" role="alert">
            <p>
              <Icon name="warn" />
              <span>{refusal.message}</span>
            </p>
            {refusal.reasons.length > 0 && (
              <ul>
                {refusal.reasons.map((r, i) => (
                  <li key={`${r.code}-${i}`}>
                    <span className="so-reason-name">{releaseReasonLabel(r.code)}</span> {r.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <ConfirmDialog
          open={confirming}
          onOpenChange={(open) => {
            if (!signOff.isPending) setConfirming(open);
          }}
          fund={fund}
          asOf={asOf}
          day={day}
          openCases={openCases}
          busy={signOff.isPending}
          onConfirm={confirm}
        />
      </>
    );
  }

  return (
    <section className="so-block so-sign" aria-labelledby="so-h-sign" data-state={state}>
      <div className="so-block-head">
        <h2 id="so-h-sign">Sign off</h2>
        <ReleaseBadge state={state} />
      </div>
      {body}
    </section>
  );
}
