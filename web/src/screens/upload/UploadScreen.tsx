/**
 * Upload and run (spec section 10, screen 2): load the day's files, see the server's
 * validation per file and row before anything runs, run the day and follow the run until
 * its cases are ready, and see the day's runs.
 *
 * The day is the one in the workspace, or the fund's next business day when nothing is
 * loaded yet. Before anyone tries, the server says whether the day can take files
 * (`GET .../intake`): when it cannot, because the previous business day is not signed off
 * or for any other reason, the screen says so in plain words, names the day holding things
 * up and offers the way to it. Files go up as soon as they are chosen or dropped; the
 * server validates the whole set it holds for the day and its answer is shown per file and
 * row, errors first (they block the run) and warnings on demand. The run is a job whose
 * progress is polled until it finishes; then everything about the day is refetched. A
 * signed-off day is locked. Viewers see the files, the checks and the runs but cannot act.
 */
import "./upload.css";

import { ApiError } from "../../api/client";
import { useDay, useIntake } from "../../api/queries";
import type { Day, ExpectedFile, FundSummary, User } from "../../api/types";
import { useUser } from "../../auth/AuthContext";
import { Icon } from "../../components/Icon";
import { StatusPill } from "../../components/Labels";
import { Lead, ProgressLine, SectionHead } from "../../components/Paper";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { count, dayLabel, plural } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { dayStatusLabel } from "../../vocabulary";
import { GenerateDay } from "../../demo/GenerateDay";
import { DropZone, useDropZone } from "./DropZone";
import { FileChecklist, Validation } from "./FileChecklist";
import { ORDER_BLOCKS, OrderNotice } from "./OrderNotice";
import { RunBlock, canAct } from "./RunBlock";

/** One sentence under the run status: what the day needs next, or what its run found. */
function runCaption(day: Day | undefined): string {
  switch (day?.status ?? null) {
    case null:
      return "Waiting for the day's files.";
    case "uploaded":
      return "Correct the files and upload them again; the run opens once they are valid.";
    case "validated":
      return "The files are valid and the day is ready to run.";
    case "running":
      return "The engine is matching, triaging and checking the day.";
    case "ready": {
      const open = typeof day?.summary?.open_cases === "number" ? day.summary.open_cases : null;
      return open != null
        ? `${plural(open, "open case")} from the latest run, ready for review.`
        : "The run has finished; its cases are ready for review.";
    }
    case "failed":
      return "The last run failed; the day can be run again.";
    case "signed_off":
      return "The NAV is signed off and the day is locked.";
    default:
      return "";
  }
}

/**
 * The lead card: the day's run status as the headline, one sentence on what comes next,
 * and the files held and their validation as pills with their words. While the day runs,
 * the card's top edge becomes the sliding 3px progress line.
 */
function RunLead({ asOf, day, expected }: { asOf: string; day: Day | undefined; expected: ExpectedFile[] | null }) {
  const status = day?.status ?? null;
  const running = status === "running";
  const report = day?.validation ?? null;
  const held = day?.files.length ?? 0;
  let checked = null;
  if (report) {
    checked = report.errors.length ? (
      <StatusPill kind="late">Errors block the run</StatusPill>
    ) : (
      <StatusPill kind="done">Files valid</StatusPill>
    );
  } else if (day) {
    checked = <StatusPill kind="neutral">Not checked yet</StatusPill>;
  }
  return (
    <Lead
      className={running ? "up-lead running" : "up-lead"}
      aria-label="Run status"
      label={`Run status, ${dayLabel(asOf)}`}
      figure={dayStatusLabel(status)}
      caption={runCaption(day)}
      foot={
        <>
          {running && <ProgressLine label="Running the day" />}
          <StatusPill kind="neutral">
            {expected ? `${count(held)} of ${count(expected.length)} files held` : `${plural(held, "file")} held`}
          </StatusPill>
          {checked}
        </>
      }
    />
  );
}

function DayPanel({ fund, asOf, user }: { fund: FundSummary; asOf: string; user: User }) {
  const { days, setDay } = useWorkspace();
  const dayQuery = useDay(fund.code, asOf);
  // Whether the day can take files, and which files it expects. If it cannot be read, the
  // screen still works from the day itself, and the server still refuses what it must.
  const intakeQuery = useIntake(fund.code, asOf);
  const intake = intakeQuery.data ?? null;
  const expected = intake?.expected_files ?? null;
  const drop = useDropZone(fund.code, asOf, expected);
  if (dayQuery.isPending || intakeQuery.isPending) return <Loading label="Loading the day" />;
  const noFiles = dayQuery.error instanceof ApiError && dayQuery.error.status === 404;
  if (dayQuery.isError && !noFiles) return <ErrorLine error={dayQuery.error} retry={() => void dayQuery.refetch()} />;
  const day = noFiles ? undefined : dayQuery.data;
  const status = day?.status ?? null;
  const locked = status === "signed_off";
  const running = status === "running";
  const orderBlocked = !!intake?.blocked && ORDER_BLOCKS.has(intake.blocked.code);
  // The demo takes no uploads: its days are generated from the same synthetic sequence.
  const demo = intake?.blocked?.code === "UPLOADS_OFF";
  const nextDay = days?.next_day ?? null;
  const mayUpload = canAct(user) && !locked && !running && !orderBlocked;
  const dropFirst = !day || status === "uploaded";
  const dropZone = <DropZone state={drop} maxFileBytes={intake?.max_file_bytes ?? null} />;
  // Once the day has run, the files are settled: their list folds away behind its verdict.
  const settled = !!day && (status === "ready" || status === "running" || status === "signed_off");
  const checklist = <FileChecklist asOf={asOf} day={day} expected={expected} />;

  return (
    <>
      <RunLead asOf={asOf} day={day} expected={expected} />
      <div className="up-grid">
        <section className="card up-block" aria-labelledby="up-h-files">
          <SectionHead label="Intake" title="Files" id="up-h-files" />
          {demo ? <GenerateDay fund={fund} user={user} /> : intake && <OrderNotice intake={intake} fundCode={fund.code} />}
          {locked && (
            <div className="up-locked">
              <span className="tile-box" aria-hidden="true">
                <Icon name="lock" />
              </span>
              <p>{dayLabel(asOf)} is signed off; its files are locked.</p>
              {nextDay && nextDay > asOf && (
                <button type="button" className="btn" onClick={() => setDay(nextDay)}>
                  Load {dayLabel(nextDay)}
                </button>
              )}
            </div>
          )}
          {!day && !orderBlocked && !demo && <p className="muted">No files have been uploaded for {dayLabel(asOf)} yet.</p>}
          {/* Until the files are valid, getting them in is the job, so the drop zone comes first. */}
          {mayUpload && dropFirst && dropZone}
          {day && <Validation day={day} expected={expected} />}
          {(day || !orderBlocked) &&
            (settled && day ? (
              <details className="up-held">
                <summary>
                  Show the {plural(day.files.length, "file")} held for {dayLabel(asOf)}
                </summary>
                {checklist}
              </details>
            ) : (
              checklist
            ))}
          {mayUpload && !dropFirst && dropZone}
          {!canAct(user) && !demo && (
            <p className="muted">Viewers can follow the day but cannot upload files or run it.</p>
          )}
        </section>
        {day && <RunBlock fund={fund} day={day} user={user} followingDay={intake?.following_day ?? null} />}
      </div>
    </>
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
  else body = <DayPanel key={`${fund.code} ${target}`} fund={fund} asOf={target} user={user} />;

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
