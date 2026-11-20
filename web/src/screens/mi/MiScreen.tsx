/**
 * Management information (spec section 10, screen 5), from `GET .../mi`.
 *
 * One job: how the fund's breaks stand and are moving, up to the day on show. The lead card
 * carries the gross open NAV impact across the period and four tiles the headline figures
 * (net impact, open breaks, average time to resolve, SLA breaches). Then open breaks by cause
 * and age (gross and net impact together), the trend across run days, the time to resolve,
 * the largest open breaks and the SLA breaches. The two exports sit in the header as quiet
 * chips. Figures behind the chart and the impact by age are on demand. Every figure is the
 * server's, computed by the engine's own MI.
 */
import "./mi.css";

import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { useMi } from "../../api/queries";
import type { Mi } from "../../api/types";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { useWorkspace } from "../../shell/workspace";
import { dayStatusLabel } from "../../vocabulary";
import { ScreenContext } from "../ScreenContext";
import { CauseAgeSection } from "./CauseAgeSection";
import { ExportButtons } from "./ExportButtons";
import { MiHeadline } from "./MiHeadline";
import { MiTrendSection } from "./MiTrendSection";
import { ResolveSection } from "./ResolveSection";
import { SlaSection } from "./SlaSection";
import { TopOpenSection } from "./TopOpenSection";

function NotRun({ mi }: { mi: Mi }) {
  const { href } = useWorkspace();
  return (
    <section className="card card-pad mi-notrun" aria-labelledby="mi-h-notrun">
      <h2 id="mi-h-notrun">Not run yet</h2>
      <p>
        <span className="mi-day-status">{dayStatusLabel(mi.day_status)}.</span> The figures for this day appear once it
        has been run; the trend below shows the days before it.
      </p>
      {mi.day_status !== "running" && (
        <p>
          <Link className="btn" to={href("/upload")}>
            Go to upload and run
          </Link>
        </p>
      )}
    </section>
  );
}

function MiBody({ mi }: { mi: Mi }) {
  const currency = mi.fund.base_currency;
  if (!mi.has_run) {
    return (
      <div className="mi-grid mi-grid-notrun">
        <NotRun mi={mi} />
        <MiTrendSection trend={mi.trend} asOf={mi.as_of} currency={currency} />
      </div>
    );
  }
  return (
    <>
      <MiHeadline mi={mi} />
      <div className="mi-grid">
        <div className="mi-area-cause">
          <CauseAgeSection grid={mi.by_cause_age} currency={currency} />
        </div>
        <div className="mi-area-resolve">
          <ResolveSection resolve={mi.time_to_resolve} />
        </div>
        <div className="mi-area-trend">
          <MiTrendSection trend={mi.trend} asOf={mi.as_of} currency={currency} />
        </div>
        <div className="mi-area-top">
          <TopOpenSection cases={mi.top_open} currency={currency} />
        </div>
        <div className="mi-area-sla">
          <SlaSection cases={mi.sla_breaches} />
        </div>
      </div>
    </>
  );
}

export function MiScreen() {
  const { fund, asOf, fundsLoading, daysLoading } = useWorkspace();
  const query = useMi(fund?.code ?? null, asOf);
  const mi = query.data;

  let body;
  if (!fund) body = fundsLoading ? <Loading label="Loading funds" /> : <Empty>No fund is set up yet.</Empty>;
  else if (!asOf)
    body = daysLoading ? (
      <Loading label="Loading business days" />
    ) : (
      <Empty>No business day has been loaded for {fund.name} yet, so there is no management information.</Empty>
    );
  else if (query.isPending) body = <Loading label="Loading management information" />;
  else if (query.isError)
    body =
      query.error instanceof ApiError && query.error.status === 404 ? (
        <Empty>{query.error.message} Management information starts once the day has been run.</Empty>
      ) : (
        <ErrorLine error={query.error} retry={() => void query.refetch()} />
      );
  else if (mi) body = <MiBody mi={mi} />;

  return (
    <section className="screen mi-screen">
      <ScreenHeader title="Management information">
        <ScreenContext />
        {fund && asOf && mi?.exports && <ExportButtons fund={fund.code} asOf={asOf} />}
      </ScreenHeader>
      {body}
    </section>
  );
}
