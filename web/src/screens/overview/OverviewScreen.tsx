/**
 * The morning overview (spec section 10, screen 1), from `GET .../overview`.
 *
 * The most important thing first: one lead card with NAV per share and the day's release
 * status (its reasons in plain words beneath), then four tiles (net impact with gross, the
 * material count, open cases and the oldest break), then the open breaks by NAV impact beside
 * every break accounted for; the rest is a glance away in two quiet panels, the age of the
 * open cases with their SLA breaches and escalations, and the days so far with what cleared.
 * Detail is on demand (checks, long lists and the trend's figures sit behind expanders),
 * and every case id opens the case in the workbench. Every figure is the server's.
 */
import "./overview.css";

import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { useOverview } from "../../api/queries";
import type { Overview } from "../../api/types";
import { ScreenHeader } from "../../components/ScreenHeader";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { timestamp } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { dayStatusLabel } from "../../vocabulary";
import { ScreenContext } from "../ScreenContext";
import { AccountedSection } from "./AccountedSection";
import { AgeingSection } from "./AgeingSection";
import { AttentionSection } from "./AttentionSection";
import { ClearedSection } from "./ClearedSection";
import { ImpactSection } from "./ImpactSection";
import { OvHead } from "./OvHead";
import { ReleaseSection } from "./ReleaseSection";
import { TilesSection } from "./TilesSection";
import { TrendSection } from "./TrendSection";

/** The way to the upload and run screen for the day on show. */
function UploadLink({ children }: { children: string }) {
  const { href } = useWorkspace();
  return (
    <p className="ov-upload-link">
      <Link className="btn" to={href("/upload")}>
        {children}
      </Link>
    </p>
  );
}

function NotRun({ overview }: { overview: Overview }) {
  const status = overview.day_status;
  let next: string;
  if (status === "running") next = "The engine is running the day now; this page fills in when it finishes.";
  else if (status === "failed") next = "The last run failed. Fix the cause and run the day again.";
  else if (status === "uploaded") next = "The day's files have errors. Upload corrected files, then run the day.";
  else next = "The day's files are loaded and valid. Run the day to see its breaks.";
  return (
    <section className="ov-block ov-notrun" aria-labelledby="ov-h-notrun">
      <OvHead label="Run" id="ov-h-notrun" title="Not run yet" />
      <p>
        <span className="ov-day-status">{dayStatusLabel(status)}.</span> {next}
      </p>
      {status !== "running" && <UploadLink>Go to upload and run</UploadLink>}
    </section>
  );
}

function OverviewBody({ overview }: { overview: Overview }) {
  const currency = overview.fund.base_currency;
  const { accounted, impact } = overview;
  const ran = overview.has_run && accounted !== null && impact !== null;
  const trend = <TrendSection trend={overview.trend} asOf={overview.as_of} currency={currency} />;
  if (!ran || !accounted || !impact) {
    return (
      <div className="ov-grid ov-grid-notrun">
        <div className="ov-area-release">
          <ReleaseSection overview={overview} />
        </div>
        <div className="ov-cols">
          <div className="ov-col ov-col-main">
            <div className="ov-area-account card">
              <NotRun overview={overview} />
            </div>
          </div>
          <div className="ov-col ov-col-side">
            <div className="ov-area-trend card">{trend}</div>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="ov-grid">
      <div className="ov-area-release">
        <ReleaseSection overview={overview} />
      </div>
      <TilesSection impact={impact} accounted={accounted} currency={currency} materialityBp={overview.fund.materiality_bp} />
      <div className="ov-cols">
        <div className="ov-col ov-col-main">
          <div className="ov-area-impact">
            <ImpactSection impact={impact} currency={currency} materialityBp={overview.fund.materiality_bp} />
          </div>
          {/* One panel for the days so far, and what this day's run cleared. */}
          <div className="ov-area-trend ov-panel card">
            {trend}
            <ClearedSection cleared={overview.cleared_today} currency={currency} />
          </div>
        </div>
        <div className="ov-col ov-col-side">
          <div className="ov-area-account">
            <AccountedSection accounted={accounted} run={overview.run} />
          </div>
          {/* One panel for how long the open cases have waited, and which are overdue or escalated. */}
          <div className="ov-area-age ov-panel card">
            <AgeingSection ageing={overview.ageing} currency={currency} />
            <AttentionSection slaBreaches={overview.sla_breaches} escalations={overview.escalations} />
          </div>
        </div>
      </div>
    </div>
  );
}

export function OverviewScreen() {
  const { fund, asOf, fundsLoading, daysLoading } = useWorkspace();
  const query = useOverview(fund?.code ?? null, asOf);
  const overview = query.data;

  let body;
  if (!fund) body = fundsLoading ? <Loading label="Loading funds" /> : <Empty>No fund is set up yet.</Empty>;
  else if (!asOf)
    body = daysLoading ? (
      <Loading label="Loading business days" />
    ) : (
      <>
        <Empty>No business day has been loaded for {fund.name} yet. Upload the first day&rsquo;s files to begin.</Empty>
        <UploadLink>Upload the first day&rsquo;s files</UploadLink>
      </>
    );
  else if (query.isPending) body = <Loading label="Loading the overview" />;
  else if (query.isError) {
    body =
      query.error instanceof ApiError && query.error.status === 404 ? (
        <>
          <Empty>{query.error.message} Upload the day&rsquo;s files to begin.</Empty>
          <UploadLink>Upload the day&rsquo;s files</UploadLink>
        </>
      ) : (
        <ErrorLine error={query.error} retry={() => void query.refetch()} />
      );
  } else if (overview) body = <OverviewBody overview={overview} />;

  return (
    <section className="screen ov-screen">
      <ScreenHeader title="Morning overview">
        <ScreenContext />
        {overview?.has_run && overview.run_at && (
          <p className="faint ov-run-line">
            Run by {overview.run_by ?? "the system"}, {timestamp(overview.run_at)}
          </p>
        )}
      </ScreenHeader>
      {body}
    </section>
  );
}
