/**
 * The run: start it, follow it, and see what it found. A run is a job on the server's
 * queue; its progress is asked for every second until it finishes, then everything about
 * the day is refetched so the strip, the day list and every screen move on together.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { FINISHED_JOB_STATUSES, invalidateDay, useJob, useStartRun } from "../../api/queries";
import type { Day, FundSummary, Job, User } from "../../api/types";
import { useAnnounce } from "../../components/Announcer";
import { Icon } from "../../components/Icon";
import { SectionHead } from "../../components/Paper";
import { ErrorLine, Loading } from "../../components/QueryState";
import { dayLabel, plural, timestamp } from "../../format";
import { useCommand } from "../../keyboard/KeyboardProvider";
import { useWorkspace } from "../../shell/workspace";
import { RunHistory } from "./RunHistory";

/** Day statuses from which a run can be started (the server's `RUNNABLE_STATUSES`). */
const RUNNABLE = new Set(["validated", "ready", "failed"]);

export function canAct(user: User): boolean {
  return user.role === "analyst" || user.role === "approver";
}

const STEPS = [
  { key: "queued", label: "Queued for the worker" },
  { key: "running", label: "Matching, triage, NAV and checks" },
  { key: "done", label: "Cases ready" },
] as const;

function Steps({ job }: { job: Job | undefined }) {
  const status = job?.status ?? "queued";
  const at = status === "running" ? 1 : FINISHED_JOB_STATUSES.has(status) ? 2 : 0;
  return (
    <ol className="up-steps" aria-label="Run progress">
      {STEPS.map((step, i) => {
        const state = i < at ? "done" : i === at ? "now" : "next";
        return (
          <li key={step.key} className={`up-step up-step-${state}`} aria-current={state === "now" ? "step" : undefined}>
            <Icon name={state === "done" ? "check" : state === "now" ? "dot" : "ring"} />
            <span>{step.label}</span>
            <span className="sr-only">{state === "done" ? " (done)" : state === "now" ? " (now)" : ""}</span>
          </li>
        );
      })}
    </ol>
  );
}

function RunProgress({ jobId, fund, asOf }: { jobId: number; fund: string; asOf: string }) {
  const job = useJob(jobId);
  const client = useQueryClient();
  const status = job.data?.status;
  const finished = !!status && FINISHED_JOB_STATUSES.has(status);

  // When the job finishes, refetch the day so the status, NAV strip and screens all move on.
  useEffect(() => {
    if (finished) void invalidateDay(client, fund, asOf);
  }, [finished, client, fund, asOf]);

  if (job.isError) return <ErrorLine error={job.error} retry={() => void job.refetch()} />;
  let text = "Queued; the worker picks it up in a moment";
  if (status === "running") text = "Running the engine: matching, triage, NAV and checks";
  if (finished) text = "Finishing";
  const retrying = job.data && job.data.attempts >= 1 && job.data.error && !finished;
  return (
    <div className="up-progress">
      <Steps job={job.data} />
      <p className="state-line" role="status">
        <span className="spinner" aria-hidden="true" />
        {text}…
      </p>
      {retrying && job.data && (
        <p className="up-retry">
          <Icon name="warn" />
          <span>
            Attempt {job.data.attempts} of {job.data.max_attempts} failed: {job.data.error} It is tried again
            automatically.
          </span>
        </p>
      )}
    </div>
  );
}

/**
 * Says the run's start and end aloud: the progress line is on screen while the job runs,
 * but its end replaces it, so a screen-reader user who moved on would otherwise not hear
 * that the cases are ready. A failed run says so in an alert of its own.
 */
function useRunAnnouncements(status: string, openCases: number | null) {
  const announce = useAnnounce();
  const previous = useRef(status);
  useEffect(() => {
    const before = previous.current;
    previous.current = status;
    if (before === status) return;
    if (status === "running") announce("The run has started.");
    else if (before === "running" && status === "ready") {
      announce(`The run has finished${openCases != null ? `: ${plural(openCases, "open case")}` : ""}. The cases are ready.`);
    }
  }, [status, openCases, announce]);
}

function NextDayHint({ asOf, followingDay }: { asOf: string; followingDay: string }) {
  const { href } = useWorkspace();
  return (
    <p className="up-next-day muted">
      {dayLabel(followingDay)} opens for its files once {dayLabel(asOf)} is{" "}
      <Link to={href("/signoff")}>signed off</Link>.
    </p>
  );
}

export function RunBlock({
  fund,
  day,
  user,
  followingDay,
}: {
  fund: FundSummary;
  day: Day;
  user: User;
  followingDay: string | null;
}) {
  const { href } = useWorkspace();
  const run = useStartRun(fund.code, day.as_of);
  const status = day.status;
  const runningJob = status === "running" ? (run.data?.job_id ?? day.job?.id ?? null) : null;
  const openCases = typeof day.summary?.open_cases === "number" ? day.summary.open_cases : null;
  const runnable = canAct(user) && RUNNABLE.has(status);
  useRunAnnouncements(status, openCases);
  useCommand(`${status === "validated" ? "Run" : "Run again"}: ${dayLabel(day.as_of)}`, () => run.mutate(), {
    group: "Upload",
    enabled: runnable && !run.isPending,
    keywords: "run the day engine start",
  });

  let body;
  if (status === "running") {
    body =
      runningJob != null ? <RunProgress jobId={runningJob} fund={fund.code} asOf={day.as_of} /> : <Loading label="Running" />;
  } else if (status === "uploaded") {
    body = <p className="muted">The run opens once the files are valid.</p>;
  } else if (status === "signed_off") {
    body = <p className="muted">The day is signed off and locked; it cannot be run again.</p>;
  } else {
    body = (
      <>
        {status === "failed" && (
          <div className="state-line error" role="alert">
            <Icon name="warn" />
            <span>The last run failed{day.error ? `: ${day.error}` : "."}</span>
          </div>
        )}
        {status === "ready" && (
          <p className="up-done">
            <Icon name="check" />
            <span>
              Run {day.run_by ? `by ${day.run_by}` : ""}
              {day.run_at ? `, ${timestamp(day.run_at)}` : ""}
              {openCases != null ? `: ${plural(openCases, "open case")}.` : "."}
            </span>
          </p>
        )}
        {status === "ready" && (
          <p className="up-next">
            <Link className="btn primary" to={href("/cases")}>
              Work the cases
            </Link>
            <Link className="btn" to={href("/overview")}>
              Open the overview
            </Link>
          </p>
        )}
        {runnable && (
          <div className="up-run">
            <button
              type="button"
              className={status === "ready" ? "btn" : "btn primary"}
              disabled={run.isPending}
              onClick={() => run.mutate()}
            >
              {status === "validated" ? "Run the day" : "Run again"}
            </button>
            {status === "ready" && (
              <p className="muted">Running again keeps the decisions that still apply and records the rest as voided.</p>
            )}
          </div>
        )}
        {run.isError && (
          <div className="state-line error" role="alert">
            <Icon name="warn" />
            <span>{run.error instanceof ApiError ? run.error.message : "The run could not start. Try again."}</span>
          </div>
        )}
        {status === "ready" && followingDay && <NextDayHint asOf={day.as_of} followingDay={followingDay} />}
      </>
    );
  }

  return (
    <section className="card up-block up-run-block" aria-labelledby="up-h-run">
      <SectionHead label="Engine" title="Run" id="up-h-run" />
      {body}
      <RunHistory fund={fund.code} asOf={day.as_of} />
    </section>
  );
}
