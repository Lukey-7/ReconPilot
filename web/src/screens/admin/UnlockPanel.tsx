/**
 * Unlocking a signed-off day, on the sign-off screen (spec section 9, owner's decision).
 *
 * Two people and a reason: an administrator asks, a different approver confirms within 24
 * hours (or declines with a note); the requester may withdraw. Only the latest signed-off
 * day, and only before the next day has run; the server checks both, and says why not in
 * its own words. Once confirmed the day is back to Ready and must be signed off again.
 *
 * Quiet unless it matters: nothing shows on a day that is not signed off and has no
 * requests; a signed-off day offers "Ask to unlock" to an administrator only; a waiting
 * request is shown to everyone, in the signal colour, with the actions the server allows
 * this person.
 */
import "./admin.css";

import * as Dialog from "@radix-ui/react-dialog";
import { type FormEvent, useId, useState } from "react";

import { ApiError } from "../../api/client";
import { useUser } from "../../auth/AuthContext";
import { Icon } from "../../components/Icon";
import { ErrorLine } from "../../components/QueryState";
import { dayLabel, timestamp } from "../../format";
import { type UnlockRequest, useAskUnlock, useConfirmUnlock, useDeclineUnlock, useUnlock } from "./api";

const MIN_REASON = 10;

const STATUS_WORDS: Record<string, string> = {
  pending: "Waiting",
  confirmed: "Unlocked",
  declined: "Declined",
  withdrawn: "Withdrawn",
  expired: "Expired unconfirmed",
};

function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return (
    <p className="form-error ad-form-error" role="alert">
      <Icon name="warn" />
      {message}
    </p>
  );
}

/** A dialog asking for a note (or a reason) before one unlock step. */
function NoteDialog({
  open,
  onOpenChange,
  title,
  description,
  label,
  required,
  minLength = 0,
  action,
  busyAction,
  busy,
  error,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  label: string;
  required: boolean;
  minLength?: number;
  action: string;
  busyAction: string;
  busy: boolean;
  error: unknown;
  onSubmit: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  const id = useId();
  const short = required && note.trim().length < Math.max(minLength, 1);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!short) onSubmit(note.trim());
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) setNote("");
        onOpenChange(next);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content className="dialog">
          <div className="dialog-head">
            <Dialog.Title>{title}</Dialog.Title>
          </div>
          <Dialog.Description className="muted">{description}</Dialog.Description>
          <form className="ad-form" onSubmit={submit}>
            <div className="ad-field">
              <label htmlFor={id}>
                {label}
                {required ? "" : " (optional)"}
              </label>
              <textarea
                id={id}
                value={note}
                maxLength={2000}
                required={required}
                onChange={(e) => setNote(e.target.value)}
                aria-describedby={minLength ? `${id}-hint` : undefined}
              />
              {minLength > 0 && (
                <span id={`${id}-hint`} className="ad-hint">
                  A sentence at least: it is kept in the audit log for good.
                </span>
              )}
            </div>
            <FormError error={error} />
            <div className="ad-dialog-actions">
              <Dialog.Close className="btn ghost" type="button" disabled={busy}>
                Cancel
              </Dialog.Close>
              <button type="submit" className="btn primary" disabled={busy || short}>
                {busy ? busyAction : action}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function History({ requests }: { requests: UnlockRequest[] }) {
  if (!requests.length) return null;
  return (
    <details className="ul-history">
      <summary>
        Earlier unlock requests ({requests.length})
      </summary>
      <ol>
        {requests.map((r) => (
          <li key={r.id}>
            <strong>{STATUS_WORDS[r.status] ?? r.status}</strong>: asked by {r.requested_by ?? "a former user"},{" "}
            {timestamp(r.requested_at)}: &ldquo;{r.reason}&rdquo;
            {r.decided_by && r.status !== "expired" && (
              <>
                {" "}
                {r.status === "withdrawn" ? "Withdrawn" : r.status === "confirmed" ? "Confirmed" : "Declined"} by{" "}
                {r.decided_by}, {timestamp(r.decided_at)}
                {r.decision_note ? `: “${r.decision_note}”` : ""}.
              </>
            )}
          </li>
        ))}
      </ol>
    </details>
  );
}

export function UnlockPanel({ fund, asOf }: { fund: string; asOf: string }) {
  const user = useUser();
  const [outcome, setOutcome] = useState<string | null>(null);
  const announce = setOutcome;
  const unlock = useUnlock(fund, asOf);
  const ask = useAskUnlock(fund, asOf);
  const confirm = useConfirmUnlock(fund, asOf);
  const decline = useDeclineUnlock(fund, asOf);
  const [dialog, setDialog] = useState<"ask" | "confirm" | "decline" | null>(null);

  if (unlock.isPending) return null;
  if (unlock.isError) {
    // A day with no files has nothing to unlock; anything else is worth saying.
    if (unlock.error instanceof ApiError && unlock.error.status === 404) return null;
    return <ErrorLine error={unlock.error} retry={() => void unlock.refetch()} />;
  }
  const state = unlock.data;
  const pending = state.pending;
  const signedOff = state.day_status === "signed_off";
  const offerAsk = state.requestable_by_me;
  const explainWhyNot = signedOff && !pending && user.is_admin && !state.unlockable && state.problem;
  if (!pending && !offerAsk && !explainWhyNot && !state.history.length && !outcome) return null;

  const close = () => setDialog(null);
  const day = dayLabel(state.as_of);

  let body;
  if (pending) {
    body = (
      <>
        <h2 id="ul-h">
          <Icon name="warn" /> Unlock requested
        </h2>
        <p>
          <strong>{pending.requested_by}</strong> asked to unlock {day} on {timestamp(pending.requested_at)}:
        </p>
        <blockquote className="ul-reason">{pending.reason}</blockquote>
        <p className="muted">
          {pending.withdrawable_by_me
            ? `A different approver must confirm by ${timestamp(pending.expires_at)}, or it expires.`
            : `It needs an approver other than ${pending.requested_by} to confirm by ${timestamp(pending.expires_at)}. Confirming reopens the day: it must then be signed off again.`}
        </p>
        <div className="ad-actions">
          {pending.declinable_by_me && (
            <button type="button" className="btn" onClick={() => setDialog("decline")}>
              Decline…
            </button>
          )}
          {pending.confirmable_by_me && (
            <button type="button" className="btn primary" onClick={() => setDialog("confirm")}>
              <Icon name="lock" /> Confirm unlock…
            </button>
          )}
          {pending.withdrawable_by_me && (
            <button
              type="button"
              className="btn"
              disabled={decline.isPending}
              onClick={() =>
                decline.mutate(
                  { id: pending.id, note: "" },
                  { onSuccess: () => announce(`The request to unlock ${day} is withdrawn.`) },
                )
              }
            >
              {decline.isPending ? "Withdrawing…" : "Withdraw request"}
            </button>
          )}
        </div>
        {dialog === null && <FormError error={decline.error} />}
      </>
    );
  } else if (offerAsk) {
    body = (
      <>
        <h2 id="ul-h">Unlock this day</h2>
        <p className="muted">
          To correct a signed-off day: you give the reason, a different approver confirms within{" "}
          {state.confirm_within_hours} hours, and the day must then be signed off again. Possible only until the next
          day runs.
        </p>
        <div className="ad-actions">
          <button type="button" className="btn" onClick={() => setDialog("ask")}>
            Ask to unlock…
          </button>
        </div>
      </>
    );
  } else if (explainWhyNot) {
    body = (
      <>
        <h2 id="ul-h">Unlocking</h2>
        <p className="muted">{state.problem}</p>
      </>
    );
  } else {
    body = <h2 id="ul-h">Unlocking</h2>;
  }

  return (
    <section className={pending ? "ul-block waiting" : "ul-block"} aria-labelledby="ul-h">
      {body}
      <p className={outcome ? "ad-done" : "sr-only"} aria-live="polite">
        {outcome && <Icon name="check" />}
        {outcome}
      </p>
      <History requests={state.history} />

      <NoteDialog
        open={dialog === "ask"}
        onOpenChange={(open) => !open && close()}
        title={`Ask to unlock ${day}?`}
        description={`The day stays signed off until an approver other than you confirms, within ${state.confirm_within_hours} hours. Then it returns to Ready: its cases can be decided again and it must be signed off again before the next day is loaded or run. Your reason is recorded in the audit log.`}
        label="Reason"
        required
        minLength={MIN_REASON}
        action="Ask to unlock"
        busyAction="Asking…"
        busy={ask.isPending}
        error={ask.error}
        onSubmit={(reason) =>
          ask.mutate(reason, {
            onSuccess: () => {
              close();
              announce(`Unlock of ${day} requested. An approver must confirm it.`);
            },
          })
        }
      />
      {pending && (
        <>
          <NoteDialog
            open={dialog === "confirm"}
            onOpenChange={(open) => !open && close()}
            title={`Unlock ${day}?`}
            description={`This reopens ${day}, signed off by ${state.signed_off_by ?? "an approver"}: the sign-off is cleared, the day returns to Ready and must be signed off again (four-eyes applies). Files, the run and decisions stand. Recorded in the audit log under your name.`}
            label="Note"
            required={false}
            action="Unlock the day"
            busyAction="Unlocking…"
            busy={confirm.isPending}
            error={confirm.error}
            onSubmit={(note) =>
              confirm.mutate(
                { id: pending.id, note },
                {
                  onSuccess: () => {
                    close();
                    announce(`${day} is unlocked. It must be signed off again.`);
                  },
                },
              )
            }
          />
          <NoteDialog
            open={dialog === "decline"}
            onOpenChange={(open) => !open && close()}
            title="Decline the unlock?"
            description={`${day} stays signed off. Say why, so ${pending.requested_by} knows what to do instead.`}
            label="Why"
            required
            action="Decline"
            busyAction="Declining…"
            busy={decline.isPending}
            error={decline.error}
            onSubmit={(note) =>
              decline.mutate(
                { id: pending.id, note },
                {
                  onSuccess: () => {
                    close();
                    announce(`The unlock of ${day} is declined.`);
                  },
                },
              )
            }
          />
        </>
      )}
    </section>
  );
}
