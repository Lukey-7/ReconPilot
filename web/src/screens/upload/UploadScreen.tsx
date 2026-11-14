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
import type { FundSummary, User } from "../../api/types";
import { useUser } from "../../auth/AuthContext";
import { Icon } from "../../components/Icon";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { dayLabel } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { dayStatusLabel } from "../../vocabulary";
import { DropZone, useDropZone } from "./DropZone";
import { FileChecklist, Validation } from "./FileChecklist";
import { ORDER_BLOCKS, OrderNotice } from "./OrderNotice";
import { RunBlock, canAct } from "./RunBlock";

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
  const nextDay = days?.next_day ?? null;
  const mayUpload = canAct(user) && !locked && !running && !orderBlocked;
  const dropFirst = !day || status === "uploaded";
  const dropZone = <DropZone state={drop} maxFileBytes={intake?.max_file_bytes ?? null} />;

  return (
    <div className="up-grid">
      <section className="up-block" aria-labelledby="up-h-files">
        <div className="up-block-head">
          <h2 id="up-h-files">Files</h2>
          <span className="tag">{dayStatusLabel(status)}</span>
        </div>
        {intake && <OrderNotice intake={intake} fundCode={fund.code} />}
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
        {!day && !orderBlocked && <p className="muted">No files have been uploaded for {dayLabel(asOf)} yet.</p>}
        {/* Until the files are valid, getting them in is the job, so the drop zone comes first. */}
        {mayUpload && dropFirst && dropZone}
        {day && <Validation day={day} expected={expected} />}
        {(day || !orderBlocked) && <FileChecklist asOf={asOf} day={day} expected={expected} />}
        {mayUpload && !dropFirst && dropZone}
        {!canAct(user) && <p className="faint">Viewers can follow the day but cannot upload files or run it.</p>}
      </section>
      {day && <RunBlock fund={fund} day={day} user={user} followingDay={intake?.following_day ?? null} />}
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
