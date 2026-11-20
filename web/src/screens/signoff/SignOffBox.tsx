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
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { useSignOff } from "../../api/queries";
import type { Day, FundSummary, Reason, ReleaseForMe, User } from "../../api/types";
import { Icon } from "../../components/Icon";
import { ReleaseBadge, releaseState } from "../../components/Labels";
import { useReturnFocus } from "../../components/returnFocus";
import { count, dayLabel, money, perShare, signedPercent, timestamp } from "../../format";
import { useCommand } from "../../keyboard/KeyboardProvider";
import { useWorkspace } from "../../shell/workspace";
import { releaseReasonLabel } from "../../vocabulary";
import { CaseIdList } from "./CaseIdList";

type Refusal = { message: string; reasons: Reason[] };

/** Where the day after a signed-off one is: generated (demo), open for files, or already loaded. */
function nextDayOf(days: ReturnType<typeof useWorkspace>["days"], asOf: string, demo: boolean) {
  if (!days) return null;
  const next = days.next_day;
  const later = days.latest_day && days.latest_day > asOf ? days.latest_day : null;
  if (next && next > asOf) return { kind: demo ? ("generate" as const) : ("open" as const), day: next };
  if (later) return { kind: "loaded" as const, day: later };
  return null;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** The tick drawn in its ring (800 ms), then the mark (450 ms). Decorative: the words say it. */
const TICK_MS = 800 + 450;

/**
 * The done moment (Paper 6.13), shown once a sign-off made here has gone through: the tick
 * drawn in a ring, a dark pill moving from "Signing off" to "Signed off", the day's summary,
 * and the next business day as the one primary. The result sentence is the box's existing
 * live region and takes focus, so it is what a screen reader hears; the pill is decorative.
 * Under reduced motion nothing animates and the pill reads "Signed off" at once.
 */
function DoneMoment({
  fund,
  asOf,
  day,
  openCases,
  demo,
  result,
}: {
  fund: FundSummary;
  asOf: string;
  day: Day | undefined;
  openCases: number | null;
  demo: boolean;
  result: ReactNode;
}) {
  const { days, setDay, href } = useWorkspace();
  const [settled, setSettled] = useState(prefersReducedMotion);
  useEffect(() => {
    if (settled) return;
    const timer = window.setTimeout(() => setSettled(true), TICK_MS);
    return () => window.clearTimeout(timer);
  }, [settled]);
  const nav = day?.nav ?? null;
  const target = nextDayOf(days, asOf, demo);

  let next;
  if (target?.kind === "generate") {
    next = (
      <>
        <p className="so-done-next">
          The next business day, <strong>{dayLabel(target.day)}</strong>, can now be generated from the demo’s synthetic
          data.
        </p>
        <Link className="btn primary so-done-go" to={href("/upload", { day: target.day })}>
          Go to the next day
        </Link>
      </>
    );
  } else if (target) {
    next = (
      <>
        <p className="so-done-next">
          {target.kind === "open" ? "The next business day, " : "A later business day, "}
          <strong>{dayLabel(target.day)}</strong>
          {target.kind === "open" ? ", is open for its files." : ", is already loaded."}
        </p>
        <button type="button" className="btn primary so-done-go" onClick={() => setDay(target.day)}>
          Go to the next day
        </button>
      </>
    );
  } else {
    next = (
      <Link className="btn primary so-done-go" to={href("/overview")}>
        Open the overview
      </Link>
    );
  }

  return (
    <div className={settled ? "so-done settled" : "so-done"}>
      <span className="so-done-pill" aria-hidden="true">
        {settled ? "Signed off" : "Signing off"}
      </span>
      <svg className="so-tick" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
        <circle className="so-tick-ring" cx="32" cy="32" r="28" pathLength={1} />
        <path className="so-tick-mark" d="M20.5 33.5l7.5 7.5 15.5-17" pathLength={1} />
      </svg>
      {result}
      <dl className="records so-done-summary">
        <div className="record">
          <dt>Fund</dt>
          <dd>{fund.name}</dd>
        </div>
        <div className="record">
          <dt>Business day</dt>
          <dd>{dayLabel(asOf)}</dd>
        </div>
        <div className="record">
          <dt>NAV, {fund.base_currency}</dt>
          <dd className="fig">{money(nav?.nav)}</dd>
        </div>
        <div className="record">
          <dt>NAV per share</dt>
          <dd className="fig">{perShare(nav?.nav_per_share)}</dd>
        </div>
        <div className="record">
          <dt>Movement</dt>
          <dd className="fig">{signedPercent(nav?.detail?.movement)}</dd>
        </div>
        {openCases != null && (
          <div className="record">
            <dt>Open cases, all decided</dt>
            <dd className="fig">{count(openCases)}</dd>
          </div>
        )}
      </dl>
      {next}
    </div>
  );
}

function NextDay({ asOf, demo }: { asOf: string; demo: boolean }) {
  const { days, setDay, href } = useWorkspace();
  if (!days) return null;
  const next = days.next_day;
  const later = days.latest_day && days.latest_day > asOf ? days.latest_day : null;
  if (next && next > asOf && demo) {
    return (
      <div className="so-next">
        <p>
          The next business day, <strong>{dayLabel(next)}</strong>, can now be generated from the demo’s synthetic data.
        </p>
        <Link className="btn" to={href("/upload", { day: next })}>
          Generate {dayLabel(next)}
        </Link>
      </div>
    );
  }
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
  keepFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fund: FundSummary;
  asOf: string;
  day: Day | undefined;
  openCases: number | null;
  busy: boolean;
  onConfirm: () => void;
  /** True once signed off: the button that opened the dialog is gone, so focus goes to the result instead. */
  keepFocus: boolean;
}) {
  const nav = day?.nav ?? null;
  const returnFocus = useReturnFocus(open);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content
          className="dialog so-dialog"
          onCloseAutoFocus={(event) => {
            if (keepFocus) event.preventDefault();
            returnFocus(event); // back to the button that opened it
          }}
        >
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
  const resultRef = useRef<HTMLParagraphElement>(null);

  const signedOff = release.signed_off || day?.status === "signed_off";
  const state = releaseState(release, signedOff);
  const blocked = signedOff ? null : blockedMessage(release, user);

  // Once signed off, the button that was focused has gone: put focus on the result, which is
  // read out, rather than letting it fall to the top of the page.
  useEffect(() => {
    if (done && signedOff) resultRef.current?.focus();
  }, [done, signedOff]);

  // The palette never signs off: it opens the same confirmation as the button.
  useCommand(
    "Sign off the NAV…",
    () => {
      setRefusal(null);
      setConfirming(true);
    },
    { group: "Sign-off", enabled: user.role === "approver" && !signedOff && !blocked && !signOff.isPending, keywords: "release lock" },
  );

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
    const result = (
      <p className="so-msg" aria-live="polite" tabIndex={-1} ref={resultRef}>
        {done ? "Signed off. " : ""}
        The NAV was signed off by <strong>{day?.signed_off_by ?? "an approver"}</strong>
        {day?.signed_off_at ? `, ${timestamp(day.signed_off_at)}` : ""}. The day is locked: its files, cases and
        decisions can no longer change.
      </p>
    );
    body = done ? (
      <DoneMoment fund={fund} asOf={asOf} day={day} openCases={openCases} demo={!!user.demo} result={result} />
    ) : (
      <>
        <div className="so-locked">
          <span className="tile-box" aria-hidden="true">
            <Icon name="lock" />
          </span>
          {result}
        </div>
        <NextDay asOf={asOf} demo={!!user.demo} />
      </>
    );
  } else {
    const isApprover = user.role === "approver";
    body = (
      <>
        {blocked ? (
          <div className="so-msg so-blocked" id={describedBy}>
            <span className="tile-box" aria-hidden="true">
              <Icon name="lock" />
            </span>
            <div className="so-blocked-body">
              <p className="so-blocked-title">{blocked.title}</p>
              <p>{blocked.text}</p>
              {blocked.reasons.map((r, i) => (
                <div key={`${r.code}-${i}`} className="so-cond-reason">
                  <p>{r.message}</p>
                  <CaseIdList ids={r.case_ids} label="Cases you decided" />
                </div>
              ))}
            </div>
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
          keepFocus={done}
        />
      </>
    );
  }

  return (
    <section className="card so-sign" aria-labelledby="so-h-sign" data-state={state}>
      <div className="so-sign-head">
        <h2 id="so-h-sign">Sign off</h2>
        <ReleaseBadge state={state} />
      </div>
      {body}
    </section>
  );
}
