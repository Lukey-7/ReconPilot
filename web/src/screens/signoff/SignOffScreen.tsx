/**
 * NAV sign-off (spec section 10, screen 4; the Ledger's sign-off page).
 *
 * One job: decide whether this day's NAV can be released, and release it. The release
 * conditions come first, each met or not in the server's own words; then who decided
 * what; beside them the sign-off action with every blocked state explained (viewer,
 * analyst, conditions unmet, four-eyes, already signed off) and the day's audit trail with
 * the server's check of the hash chain. After sign-off the day shows as locked and the
 * next business day is offered for its files. Every figure and status is the server's.
 */
import "./signoff.css";

import { ApiError } from "../../api/client";
import { useDay, useOverview, useRelease } from "../../api/queries";
import { useUser } from "../../auth/AuthContext";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { useWorkspace } from "../../shell/workspace";
import { UnlockPanel } from "../admin/UnlockPanel";
import { ScreenContext } from "../ScreenContext";
import { AuditTrail } from "./AuditTrail";
import { Conditions } from "./Conditions";
import { SignOffBox } from "./SignOffBox";
import { WhoDecided } from "./WhoDecided";

function WhoDecidedArea({ fund, asOf }: { fund: string; asOf: string }) {
  const overview = useOverview(fund, asOf);
  if (overview.isPending) return <Loading label="Loading the day's decisions" />;
  if (overview.isError) return <ErrorLine error={overview.error} retry={() => void overview.refetch()} />;
  const impact = overview.data.impact;
  if (!overview.data.has_run || !impact) {
    return (
      <section className="so-block" aria-labelledby="so-h-who">
        <h2 id="so-h-who">Who decided what</h2>
        <p className="muted">The day has not run, so it has no cases to decide yet.</p>
      </section>
    );
  }
  return <WhoDecided cases={impact.cases} />;
}

export function SignOffScreen() {
  const { fund, asOf, fundsLoading, daysLoading } = useWorkspace();
  const user = useUser();
  const code = fund?.code ?? null;
  const release = useRelease(code, asOf);
  const day = useDay(code, asOf);
  const overview = useOverview(code, asOf);

  let body;
  if (!fund) body = fundsLoading ? <Loading label="Loading funds" /> : <Empty>No fund is set up yet.</Empty>;
  else if (!asOf)
    body = daysLoading ? (
      <Loading label="Loading business days" />
    ) : (
      <Empty>No business day has been loaded for {fund.name} yet, so there is nothing to sign off.</Empty>
    );
  else if (day.error instanceof ApiError && day.error.status === 404)
    body = <Empty>{day.error.message} There is nothing to sign off until the day&rsquo;s files are loaded and run.</Empty>;
  else if (release.isPending) body = <Loading label="Checking the release conditions" />;
  else if (release.isError) body = <ErrorLine error={release.error} retry={() => void release.refetch()} />;
  else {
    const openCases = overview.data?.accounted?.open_cases ?? null;
    body = (
      <div className="so-grid">
        <div className="so-col so-col-main">
          <div className="so-area-conds">
            <Conditions
              release={release.data}
              overview={overview.data}
              role={user.role}
              signedOffBy={day.data?.signed_off_by ?? null}
            />
          </div>
          <div className="so-area-who">
            <WhoDecidedArea fund={fund.code} asOf={asOf} />
          </div>
        </div>
        <div className="so-col so-col-side">
          <div className="so-area-sign">
            <SignOffBox
              fund={fund}
              asOf={asOf}
              release={release.data}
              day={day.data}
              openCases={openCases}
              user={user}
            />
            <UnlockPanel fund={fund.code} asOf={asOf} />
          </div>
          <div className="so-area-audit">
            <AuditTrail fund={fund.code} asOf={asOf} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <section className="screen so-screen">
      <ScreenHeader title="NAV sign-off">
        <ScreenContext />
      </ScreenHeader>
      {body}
    </section>
  );
}
