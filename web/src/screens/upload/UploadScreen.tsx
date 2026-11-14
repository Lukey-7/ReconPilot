/**
 * Upload and run (spec section 10, screen 2), the part phase 2 needs so a whole day can be
 * worked in the browser: load the day's files, see the server's validation, run the day
 * and follow the run until its cases are ready.
 *
 * The day is the one in the workspace, or the fund's next business day when nothing is
 * loaded yet. Files go up as soon as they are chosen or dropped; the server validates the
 * whole set it holds for the day and its answer is shown per file and row, errors first
 * (they block the run) and warnings on demand. The run is a job: its progress is polled
 * until it finishes, then everything about the day is refetched. Days are worked in
 * order and a signed-off day is locked; the server enforces both and its refusals are
 * shown in its own words. Viewers see the files and status but cannot act.
 */
import "./upload.css";

import { useQueryClient } from "@tanstack/react-query";
import { type DragEvent, useEffect, useId, useState } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { FINISHED_JOB_STATUSES, invalidateDay, useDay, useJob, useStartRun, useUploadFiles } from "../../api/queries";
import type { Day, FundSummary, User, ValidationIssue } from "../../api/types";
import { useUser } from "../../auth/AuthContext";
import { Icon } from "../../components/Icon";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { count, dayLabel, plural, timestamp } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { dayStatusLabel } from "../../vocabulary";

/** Day statuses from which a run can be started (the server's `RUNNABLE_STATUSES`). */
const RUNNABLE = new Set(["validated", "ready", "failed"]);

function canAct(user: User): boolean {
  return user.role === "analyst" || user.role === "approver";
}

function sizeText(bytes: number): string {
  if (bytes < 1024) return `${count(bytes)} B`;
  return `${(bytes / 1024).toLocaleString("en-GB", { maximumFractionDigits: 1 })} KB`;
}

function issueWhere(issue: ValidationIssue): string {
  return issue.row != null ? `${issue.file}, row ${count(issue.row)}` : issue.file;
}

function IssueList({ issues }: { issues: ValidationIssue[] }) {
  return (
    <ul className="up-issues">
      {issues.map((issue, i) => (
        <li key={`${issue.file}-${issue.row ?? "file"}-${i}`}>
          <span className="up-issue-where mono">{issueWhere(issue)}</span>
          <span>{issue.message}</span>
        </li>
      ))}
    </ul>
  );
}

function HeldFiles({ day }: { day: Day }) {
  if (!day.files.length) return null;
  return (
    <div className="table-wrap">
      <table className="data-table up-files">
        <caption>Files held for {dayLabel(day.as_of)}</caption>
        <thead>
          <tr>
            <th scope="col">File</th>
            <th scope="col" className="num">
              Size
            </th>
            <th scope="col">SHA-256</th>
            <th scope="col">Uploaded</th>
          </tr>
        </thead>
        <tbody>
          {day.files.map((f) => (
            <tr key={f.kind}>
              <td className="mono">{f.filename}</td>
              <td className="num">{sizeText(f.size_bytes)}</td>
              <td className="mono faint" title={f.sha256}>
                {f.sha256.slice(0, 12)}…
              </td>
              <td>
                {f.uploaded_by ?? "unknown"}
                {f.uploaded_at ? `, ${timestamp(f.uploaded_at)}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Validation({ day }: { day: Day }) {
  const report = day.validation;
  if (!report) return null;
  const { errors, warnings } = report;
  return (
    <div className="up-validation" aria-live="polite">
      {errors.length > 0 ? (
        <div className="up-errors" role="alert">
          <p className="up-verdict">
            <Icon name="cross" />
            {plural(errors.length, "problem")} {errors.length === 1 ? "blocks" : "block"} the run.
            Correct the files and upload them again.
          </p>
          <IssueList issues={errors} />
        </div>
      ) : (
        <p className="up-verdict up-ok">
          <Icon name="check" />
          The files are valid{warnings.length ? ", with warnings that do not block the run" : ""}.
        </p>
      )}
      {warnings.length > 0 && (
        <details className="up-warnings">
          <summary>
            {plural(warnings.length, "warning")}
          </summary>
          <IssueList issues={warnings} />
        </details>
      )}
    </div>
  );
}

function DropZone({ fund, asOf }: { fund: string; asOf: string }) {
  const upload = useUploadFiles(fund, asOf);
  const [over, setOver] = useState(false);
  const inputId = useId();
  const hintId = useId();

  function send(list: FileList | null) {
    const files = list ? Array.from(list) : [];
    if (!files.length) return;
    upload.mutate(files);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setOver(false);
    send(event.dataTransfer.files);
  }

  return (
    <div
      className={over ? "up-drop over" : "up-drop"}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <label htmlFor={inputId} className="up-drop-label">
        Choose the day&rsquo;s files
      </label>
      <p id={hintId} className="muted">
        Or drop them here. Send the whole set or only the files that changed; each upload replaces the files of the
        same name and the day is validated again.
      </p>
      <input
        id={inputId}
        type="file"
        multiple
        accept=".csv,text/csv"
        aria-describedby={hintId}
        disabled={upload.isPending}
        onChange={(event) => {
          send(event.target.files);
          event.target.value = ""; // choosing the same files again uploads them again
        }}
      />
      {upload.isPending && (
        <p className="state-line" role="status">
          <span className="spinner" aria-hidden="true" />
          Uploading and validating…
        </p>
      )}
      {upload.isError && (
        <div className="state-line error" role="alert">
          <Icon name="warn" />
          <span>{upload.error instanceof ApiError ? upload.error.message : "The upload failed. Try again."}</span>
        </div>
      )}
    </div>
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
  return (
    <p className="state-line" role="status">
      <span className="spinner" aria-hidden="true" />
      {text}…
    </p>
  );
}

function RunBlock({ fund, day, user }: { fund: FundSummary; day: Day; user: User }) {
  const { href } = useWorkspace();
  const run = useStartRun(fund.code, day.as_of);
  const status = day.status;
  const runningJob = status === "running" ? (run.data?.job_id ?? day.job?.id ?? null) : null;
  const openCases = typeof day.summary?.open_cases === "number" ? day.summary.open_cases : null;

  let body;
  if (status === "running") {
    body = runningJob != null ? <RunProgress jobId={runningJob} fund={fund.code} asOf={day.as_of} /> : <Loading label="Running" />;
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
        {canAct(user) && RUNNABLE.has(status) && (
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
              <p className="faint">Running again keeps the decisions that still apply and records the rest as voided.</p>
            )}
          </div>
        )}
        {run.isError && (
          <div className="state-line error" role="alert">
            <Icon name="warn" />
            <span>{run.error instanceof ApiError ? run.error.message : "The run could not start. Try again."}</span>
          </div>
        )}
      </>
    );
  }

  return (
    <section className="up-block" aria-labelledby="up-h-run">
      <h2 id="up-h-run">Run</h2>
      {body}
    </section>
  );
}

function DayPanel({ fund, asOf, user }: { fund: FundSummary; asOf: string; user: User }) {
  const { days, setDay } = useWorkspace();
  const dayQuery = useDay(fund.code, asOf);
  if (dayQuery.isPending) return <Loading label="Loading the day" />;
  const noFiles = dayQuery.error instanceof ApiError && dayQuery.error.status === 404;
  if (dayQuery.isError && !noFiles) return <ErrorLine error={dayQuery.error} retry={() => void dayQuery.refetch()} />;
  const day = noFiles ? undefined : dayQuery.data;
  const status = day?.status ?? null;
  const locked = status === "signed_off";
  const running = status === "running";
  const nextDay = days?.next_day ?? null;

  return (
    <div className="up-grid">
      <section className="up-block" aria-labelledby="up-h-files">
        <div className="up-block-head">
          <h2 id="up-h-files">Files</h2>
          <span className="tag">{dayStatusLabel(status)}</span>
        </div>
        {locked && (
          <div className="up-locked">
            <p>
              <Icon name="lock" /> {dayLabel(asOf)} is signed off; its files are locked.
            </p>
            {nextDay && nextDay > asOf && (
              <button type="button" className="btn" onClick={() => setDay(nextDay)}>
                Load {dayLabel(nextDay)}
              </button>
            )}
          </div>
        )}
        {!day && <p className="muted">No files have been uploaded for {dayLabel(asOf)} yet.</p>}
        {day && <HeldFiles day={day} />}
        {day && <Validation day={day} />}
        {canAct(user) && !locked && !running && <DropZone fund={fund.code} asOf={asOf} />}
        {!canAct(user) && <p className="faint">Viewers can follow the day but cannot upload files or run it.</p>}
      </section>
      {day && <RunBlock fund={fund} day={day} user={user} />}
    </div>
  );
}

export function UploadScreen() {
  const { fund, asOf, days, fundsLoading, daysLoading } = useWorkspace();
  const user = useUser();
  // The workspace's day, or the next business day when the fund has none loaded yet.
  const target = asOf ?? days?.next_day ?? null;

  let body;
  if (!fund) body = fundsLoading ? <Loading label="Loading funds" /> : <Empty>No fund is set up yet.</Empty>;
  else if (!target)
    body = daysLoading ? <Loading label="Loading business days" /> : <Empty>No business day is open for files.</Empty>;
  else body = <DayPanel fund={fund} asOf={target} user={user} />;

  return (
    <section className="screen up-screen">
      <ScreenHeader title="Upload and run">
        {fund && (
          <p className="muted">
            {fund.name}, {target ? dayLabel(target) : "no business day open"}
          </p>
        )}
      </ScreenHeader>
      {body}
    </section>
  );
}
