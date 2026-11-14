/**
 * The day's runs, newest first: who started each, when, how it ended and what it found.
 * A re-run says what happened to the decisions already made. Asked again while a run is
 * under way, so the newest row moves from queued to finished on its own.
 */
import { useDayRuns } from "../../api/queries";
import type { DayRun } from "../../api/types";
import { Icon } from "../../components/Icon";
import { count, dayLabel, plural, timestamp } from "../../format";
import { runStatusLabel } from "../../vocabulary";

function seconds(value: number | null): string {
  if (value == null) return "";
  if (value < 60) return `${value.toLocaleString("en-GB", { maximumFractionDigits: 1 })} s`;
  return `${Math.floor(value / 60)} min ${Math.round(value % 60)} s`;
}

function StatusWord({ run }: { run: DayRun }) {
  const icon = run.status === "done" ? "check" : run.status === "failed" ? "cross" : "clock";
  const tone = run.status === "done" ? "up-res-ok" : run.status === "failed" ? "up-res-bad" : "";
  return (
    <span className={`up-res ${tone}`}>
      <Icon name={icon} /> {runStatusLabel(run.status)}
    </span>
  );
}

function Outcome({ run }: { run: DayRun }) {
  if (run.skipped) return <span className="faint">Not needed: {run.skipped}.</span>;
  if (run.status === "failed") return <span>{run.error ?? "The run failed."}</span>;
  if (!run.outcome) {
    if (run.error) {
      return (
        <span>
          Attempt {count(run.attempts)} of {count(run.max_attempts)} failed: {run.error}
        </span>
      );
    }
    return <span className="faint">Under way</span>;
  }
  const o = run.outcome;
  const parts = [`${plural(o.open_cases ?? 0, "open case")}`];
  const detail = [];
  if (o.new_cases != null) detail.push(`${count(o.new_cases)} new`);
  if (o.carried_cases) detail.push(`${count(o.carried_cases)} carried`);
  if (o.cleared_today) detail.push(`${count(o.cleared_today)} cleared`);
  const rerun = [];
  if (o.decisions_reapplied) rerun.push(`${plural(o.decisions_reapplied, "decision")} kept`);
  if (o.decisions_voided) rerun.push(`${plural(o.decisions_voided, "decision")} voided`);
  if (o.cases_withdrawn) rerun.push(`${plural(o.cases_withdrawn, "case")} withdrawn`);
  return (
    <span>
      {parts.join("")}
      {detail.length ? ` (${detail.join(", ")})` : ""}
      {o.breaks != null ? `; ${plural(o.breaks, "break")} found` : ""}.
      {rerun.length ? <span className="up-rerun"> Re-run: {rerun.join(", ")}.</span> : null}
    </span>
  );
}

export function RunHistory({ fund, asOf }: { fund: string; asOf: string }) {
  const runs = useDayRuns(fund, asOf);
  // History is detail: when it cannot be read, the rest of the screen still stands.
  const list = runs.data?.runs ?? [];
  if (!list.length) return null;
  return (
    <details className="up-history" open={list.length <= 3}>
      <summary>
        {list.length === 1 ? "1 run" : `${count(list.length)} runs`} of {dayLabel(asOf)}
      </summary>
      <div className="table-wrap">
        <table className="data-table up-runs">
          <caption className="sr-only">Runs of {dayLabel(asOf)}, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Started</th>
              <th scope="col">Result</th>
              <th scope="col">Found</th>
              <th scope="col" className="num">
                Took
              </th>
            </tr>
          </thead>
          <tbody>
            {list.map((run) => (
              <tr key={run.job_id}>
                <td>
                  {timestamp(run.queued_at)}
                  <span className="up-by">
                    {run.started_by ?? "unknown"}
                    {run.rerun ? ", re-run" : ""}
                  </span>
                </td>
                <td>
                  <StatusWord run={run} />
                </td>
                <td>
                  <Outcome run={run} />
                </td>
                <td className="num">{seconds(run.duration_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
