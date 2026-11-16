/**
 * The decision bar, always at the foot of the case pane: Approve, Reject (a note is
 * required) and Reclassify (pick a cause). Every decision quotes the case's `version`; the
 * server refuses a stale one (someone else decided first) or one on a locked day with 409,
 * and the bar says so in plain words, refetches the day and keeps the person's note.
 *
 * Keys: a approves, r rejects (or moves to the note when it is empty), c moves to the cause,
 * Ctrl+Enter in the note submits the decision being made. Viewers get no bar, only a line.
 */
import { type KeyboardEvent, useId, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { useDecision } from "../../api/queries";
import type { CaseDetail, DecisionRequest, RoleName } from "../../api/types";
import { useAnnounce } from "../../components/Announcer";
import { Icon } from "../../components/Icon";
import { Kbd } from "../../components/Kbd";
import { StatusLabel } from "../../components/Labels";
import { useCommand, useShortcut } from "../../keyboard/KeyboardProvider";
import { CAUSES, CAUSE_LABELS, causeLabel, roleLabel, statusLabel } from "../../vocabulary";

type Armed = "reject" | "reclassify" | null;

type Outcome =
  | { kind: "done"; message: string }
  | { kind: "refused"; status: number; message: string; sentVersion: number }
  | { kind: "invalid"; message: string };

/** Why this person cannot decide this case right now, or null if they can. */
export function readOnlyReason(detail: CaseDetail, role: RoleName, signedOffBy: string | null): string | null {
  if (role === "viewer") return "Read-only. Viewers can see every case and decision but cannot act on them.";
  if (!detail.is_open) return "This case has cleared; there is nothing to decide.";
  if (detail.day_status === "signed_off") {
    return `The NAV for this day is signed off${signedOffBy ? ` by ${signedOffBy}` : ""}. Its cases are locked.`;
  }
  if (detail.day_status === "running") return "The day is being run again. Decisions open when the run is ready.";
  if (detail.day_status !== "ready") return "Decisions open once the day's run is ready.";
  return null;
}

function StateLine({ detail }: { detail: CaseDetail }) {
  const c = detail.case;
  if (c.status === "PENDING") {
    return (
      <p className="wb-state">
        <StatusLabel status="PENDING" />
        <span>Nobody has decided this case yet.</span>
      </p>
    );
  }
  return (
    <p className="wb-state">
      <StatusLabel status={c.status} />
      <span>
        {c.final_category && c.status === "RECLASSIFIED" && (
          <>
            as <strong>{causeLabel(c.final_category)}</strong>,{" "}
          </>
        )}
        by <strong>{c.reviewed_by || "unknown"}</strong>
        {c.reviewed_role ? ` (${roleLabel(c.reviewed_role)})` : ""}
      </span>
      {c.review_note && <q className="wb-state-note">{c.review_note}</q>}
    </p>
  );
}

function refusalText(outcome: Extract<Outcome, { kind: "refused" }>, detail: CaseDetail): string {
  if (outcome.status === 409) {
    if (detail.day_status === "signed_off") return "Not recorded: the day was signed off before your decision arrived, so its cases are locked.";
    if (!detail.is_open) return "Not recorded: the case cleared before your decision arrived.";
    if (detail.version != null && detail.version > outcome.sentVersion) {
      const who = detail.case.reviewed_by;
      return `Not recorded: ${who ? `${who} decided` : "someone else changed"} this case while you had it open. Its current decision is shown above; your note is kept if you still want to decide.`;
    }
  }
  return `Not recorded: ${outcome.message}`;
}

export interface DecisionBarProps {
  detail: CaseDetail;
  fund: string;
  asOf: string;
  role: RoleName;
  signedOffBy: string | null;
  /** Before a shortcut acts: returns true if it opened another case instead (the first press). */
  beforeShortcut: () => boolean;
}

export function DecisionBar({ detail, fund, asOf, role, signedOffBy, beforeShortcut }: DecisionBarProps) {
  const c = detail.case;
  const decision = useDecision(fund, asOf);
  const announce = useAnnounce();
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const causeRef = useRef<HTMLSelectElement>(null);
  const [note, setNote] = useState("");
  const [armed, setArmed] = useState<Armed>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const aiDisagrees = c.ai_status === "ACCEPTED" && !!c.ai_category && c.ai_category !== c.category;
  const current = c.final_category ?? c.category;
  const [cause, setCause] = useState<string>(() =>
    aiDisagrees && c.ai_category ? c.ai_category : (CAUSES.find((k) => k !== current) ?? "UNKNOWN"),
  );
  const ids = useId();
  const noteId = `${ids}-note`;
  const noteHelpId = `${ids}-note-help`;

  const reason = readOnlyReason(detail, role, signedOffBy);
  const canAct = reason === null;
  const busy = decision.isPending;

  const send = (request: Omit<DecisionRequest, "version" | "note">) => {
    if (busy || detail.version == null) return;
    const sentVersion = detail.version;
    const body: DecisionRequest = { ...request, note: note.trim(), version: sentVersion };
    setOutcome(null);
    decision.mutate(
      { caseId: detail.case_id, request: body },
      {
        onSuccess: (updated) => {
          const verb = statusLabel(updated.case.status);
          const as =
            updated.case.status === "RECLASSIFIED" && updated.case.final_category
              ? ` as ${causeLabel(updated.case.final_category)}`
              : "";
          const message = `${verb} ${updated.case_id}${as}. Recorded in the audit log.`;
          setOutcome({ kind: "done", message });
          // The line above can move as the bar changes to its decided state, so the result is
          // also read out from the shell's live region, worded for a listener.
          announce(`Decision recorded: ${verb} ${updated.case_id}${as}.`);
          setNote("");
          setArmed(null);
        },
        onError: (error) => {
          const status = error instanceof ApiError ? error.status : 0;
          const message = error instanceof Error ? error.message : "The decision could not be recorded.";
          if (status === 422) setOutcome({ kind: "invalid", message });
          else setOutcome({ kind: "refused", status, message, sentVersion });
        },
      },
    );
  };

  const approve = () => send({ decision: "approve" });

  const reject = () => {
    if (!note.trim()) {
      setArmed("reject");
      setOutcome({ kind: "invalid", message: "A rejection needs a note explaining why. Write it, then press Reject again." });
      noteRef.current?.focus();
      return;
    }
    send({ decision: "reject" });
  };

  const reclassify = () => send({ decision: "reclassify", category: cause });

  const onNoteKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      if (armed === "reject") reject();
      else if (armed === "reclassify") reclassify();
      else approve();
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.currentTarget.blur();
    }
  };

  /** r: reject at once when the note is written, otherwise move to the note. */
  const startReject = () => {
    if (note.trim()) reject();
    else {
      setArmed("reject");
      noteRef.current?.focus();
    }
  };

  /** c: move to the cause. */
  const startReclassify = () => {
    setArmed("reclassify");
    causeRef.current?.focus();
  };

  // The keys act on the queue's cursor (opening that case first if it is not the open one);
  // the palette's actions name the open case, so they act on it whatever the cursor is on.
  const shortcutOptions = { group: "Cases", enabled: canAct };
  useShortcut(
    "a",
    () => {
      if (!beforeShortcut()) approve();
    },
    { ...shortcutOptions, description: "Approve the open case" },
  );
  useShortcut(
    "r",
    () => {
      if (!beforeShortcut()) startReject();
    },
    { ...shortcutOptions, description: "Reject the open case (moves to the note)" },
  );
  useShortcut(
    "c",
    () => {
      if (!beforeShortcut()) startReclassify();
    },
    { ...shortcutOptions, description: "Reclassify the open case (moves to the cause)" },
  );
  useCommand(`Approve ${detail.case_id}`, approve, { ...shortcutOptions, keys: "a" });
  useCommand(`Reject ${detail.case_id}…`, startReject, { ...shortcutOptions, keys: "r" });
  useCommand(`Reclassify ${detail.case_id}…`, startReclassify, { ...shortcutOptions, keys: "c" });

  const decided = c.status !== "PENDING";
  const outcomeLine =
    outcome == null ? null : outcome.kind === "done" ? (
      <p className="wb-outcome wb-outcome-done">
        <Icon name="check" />
        {outcome.message}
      </p>
    ) : (
      <p className="wb-outcome wb-outcome-error" role="alert">
        <Icon name="warn" />
        {outcome.kind === "refused" ? refusalText(outcome, detail) : outcome.message}
      </p>
    );

  if (role === "viewer") {
    return (
      <section className="wb-decision" aria-label="Decision">
        <StateLine detail={detail} />
        <p className="wb-readonly">
          <Icon name="eye" />
          {reason}
        </p>
      </section>
    );
  }

  if (!canAct) {
    return (
      <section className="wb-decision" aria-label="Decision">
        <StateLine detail={detail} />
        {outcomeLine}
        <p className="wb-readonly">
          <Icon name="lock" />
          {reason}
        </p>
      </section>
    );
  }

  const noteInvalid = armed === "reject" && outcome?.kind === "invalid" && !note.trim();
  return (
    <section className="wb-decision" aria-labelledby={`${ids}-h`} aria-busy={busy || undefined}>
      <h3 id={`${ids}-h`} className="sr-only">
        Decision on {detail.case_id}
      </h3>
      <StateLine detail={detail} />
      <p className="wb-advice">
        Approve confirms the rules&rsquo; cause, <strong>{causeLabel(c.category)}</strong>.
        {aiDisagrees && c.ai_category && (
          <>
            {" "}
            The AI reads it as <strong>{causeLabel(c.ai_category)}</strong>; to record that, reclassify.
          </>
        )}
        {decided && " A new decision replaces this one and is logged separately."}
      </p>
      {c.escalated && role !== "approver" && (
        <p className="wb-advice wb-advice-esc">
          <Icon name="warn" />
          {c.reviewed_role === "approver"
            ? "Escalated: an approver has decided this case. A decision from you replaces theirs, and the case then needs an approver again before sign-off."
            : "Escalated: an approver must decide this case before sign-off. Your decision is recorded but does not clear the escalation."}
        </p>
      )}
      <div className="wb-note-field">
        <label htmlFor={noteId}>
          Note <span className={armed === "reject" ? "wb-required" : "faint"}>(required to reject)</span>
        </label>
        <textarea
          id={noteId}
          ref={noteRef}
          rows={1}
          value={note}
          maxLength={2000}
          placeholder="What you checked, and what you found"
          aria-describedby={noteHelpId}
          aria-invalid={noteInvalid || undefined}
          aria-required={armed === "reject" || undefined}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={onNoteKeyDown}
        />
        <span id={noteHelpId} className="sr-only">
          Ctrl and Enter submits {armed === "reject" ? "the rejection" : armed === "reclassify" ? "the reclassification" : "an approval"}.
        </span>
      </div>
      {outcomeLine}
      <div className="wb-actions">
        <button type="button" className="btn primary" onClick={approve} disabled={busy} aria-keyshortcuts="a">
          <Icon name="check" />
          Approve <Kbd keys="a" />
        </button>
        <button
          type="button"
          className={`btn wb-reject${armed === "reject" ? " wb-armed" : ""}`}
          onClick={reject}
          disabled={busy}
          aria-keyshortcuts="r"
        >
          <Icon name="cross" />
          Reject <Kbd keys="r" />
        </button>
        <span className={`wb-reclass${armed === "reclassify" ? " wb-armed" : ""}`}>
          <label htmlFor={`${ids}-cause`} className="sr-only">
            Reclassify as
          </label>
          <select
            id={`${ids}-cause`}
            ref={causeRef}
            value={cause}
            onChange={(e) => {
              setCause(e.target.value);
              setArmed("reclassify");
            }}
          >
            {CAUSES.map((k) => (
              <option key={k} value={k}>
                {CAUSE_LABELS[k]}
              </option>
            ))}
          </select>
          <button type="button" className="btn" onClick={reclassify} disabled={busy} aria-keyshortcuts="c">
            <Icon name="reclass" />
            Reclassify <Kbd keys="c" />
          </button>
        </span>
      </div>
    </section>
  );
}
