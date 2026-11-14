/**
 * The public demo's way in: one click makes the visitor a fund of their own (a hard
 * working week of synthetic data, the first days already worked and signed off, the last
 * one waiting) and signs them in as its analyst. There are no passwords in the demo.
 *
 * A visitor whose session has ended can return to their own fund from the same browser for
 * as long as the fund lives (the server knows it from a cookie); starting afresh is then
 * the second choice.
 */
import "./demo.css";

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../api/client";
import type { Instance } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { dayLabel } from "../format";

/**
 * `onBusy` tells the sign-in screen a demo is starting, so it leaves the navigation to the
 * visitor's fund to this component rather than returning to an earlier page.
 */
export function TryDemo({ instance, onBusy }: { instance: Instance; onBusy?: (busy: boolean) => void }) {
  const { startDemo, resumeDemo } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusyState] = useState(false);
  const setBusy = (value: boolean) => {
    setBusyState(value);
    onBusy?.(value);
  };
  const [error, setError] = useState<string | null>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  const week = instance.demo?.week ?? [];
  const resume = instance.demo?.resume ?? null;

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  async function start(again: boolean) {
    setBusy(true);
    setError(null);
    try {
      const started = again ? await resumeDemo() : await startDemo();
      navigate(`/overview?fund=${encodeURIComponent(started.fund)}`, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The demo could not start. Try again.");
      setBusy(false);
    }
  }

  return (
    <>
      <h1 id="signin-title">Try the demo</h1>
      <p className="muted signin-lede">
        Work a fund-servicing desk’s morning: breaks ranked by NAV impact, an AI second opinion with a drafted custodian
        query, four-eyes sign-off, MI and an audit trail you can verify.
      </p>
      {error && (
        <p className="form-error" role="alert" tabIndex={-1} ref={errorRef}>
          <Icon name="warn" /> {error}
        </p>
      )}
      <ul className="demo-points">
        <li>
          A fund of your own with a hard week of data
          {week.length ? ` (${dayLabel(week[0])} to ${dayLabel(week[week.length - 1])})` : ""}: the first days are
          worked and signed off, the last one waits for you.
        </li>
        <li>Four one-click users: an analyst, two approvers and a viewer. Switch between them at any time.</li>
        <li>Nothing you do is seen by other visitors.</li>
      </ul>
      {resume ? (
        <>
          <button type="button" className="btn primary signin-submit" onClick={() => void start(true)} disabled={busy}>
            Carry on with {resume.fund}
          </button>
          <button type="button" className="btn signin-submit" onClick={() => void start(false)} disabled={busy}>
            {busy ? "Preparing…" : "Start a new demo"}
          </button>
        </>
      ) : (
        <button type="button" className="btn primary signin-submit" onClick={() => void start(false)} disabled={busy}>
          {busy ? "Preparing your fund…" : "Try the demo"}
        </button>
      )}
    </>
  );
}
