/**
 * NAV sign-off (spec section 10, screen 4; the Ledger's sign-off page).
 *
 * One job: decide whether this day's NAV can be released, and release it. The lead card
 * says where the release stands and whether the four-eyes rule is satisfied; then the
 * release conditions, each met or not in the server's own words; then who decided what;
 * beside them the sign-off action with every blocked state explained (viewer, analyst,
 * conditions unmet, four-eyes, already signed off) and the day's audit trail with the
 * server's check of the hash chain. After sign-off the day shows as locked and the next
 * business day is offered. Every figure and status is the server's.
 */
import "./signoff.css";

import { ApiError } from "../../api/client";
import { useDay, useOverview, useRelease } from "../../api/queries";
import type { Overview, ReleaseForMe, RoleName } from "../../api/types";
import { useUser } from "../../auth/AuthContext";
import { type StatusKind, StatusPill, releaseState } from "../../components/Labels";
import { Lead, SectionHead } from "../../components/Paper";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { count } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { RELEASE_LABELS } from "../../vocabulary";
import { UnlockPanel } from "../admin/UnlockPanel";
import { ScreenContext } from "../ScreenContext";
import { AuditTrail } from "./AuditTrail";
import { Conditions, conditionsFor } from "./Conditions";
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
        <SectionHead label="Four-eyes" title="Who decided what" id="so-h-who" />
        <p className="card empty-state">The day has not run, so it has no cases to decide yet.</p>
      </section>
    );
  }
  return <WhoDecided cases={impact.cases} />;
}

const FOUR_EYES: Record<string, { kind: StatusKind; word: string }> = {
  met: { kind: "done", word: "Four-eyes met" },
  unmet: { kind: "late", word: "Four-eyes not met" },
  na: { kind: "neutral", word: "Four-eyes: for the signer" },
};

/**
 * The lead card: the release status as the headline, whether the four-eyes rule is
 * satisfied as its caption, and the conditions met and four-eyes as pills with their words.
 * Read from the same conditions the list below shows, so the two never disagree.
 */
function ReleaseLead({
  release,
  overview,
  role,
  signedOff,
  signedOffBy,
}: {
  release: ReleaseForMe;
  overview: Overview | undefined;
  role: RoleName;
  signedOff: boolean;
  signedOffBy: string | null;
}) {
  const conditions = conditionsFor(release, overview, role, signedOffBy);
  const fourEyes = conditions.find((c) => c.code === "FOUR_EYES");
  const day = conditions.filter((c) => c.code !== "FOUR_EYES");
  const met = day.filter((c) => c.state === "met").length;
  const state = releaseState(release, signedOff);

  let caption: string;
  if (!fourEyes) caption = "Four-eyes is checked once the day has run.";
  else if (signedOff)
    caption = `Four-eyes satisfied at sign-off: ${signedOffBy ?? "the approver who signed off"} decided none of the day's open cases.`;
  else if (fourEyes.state === "met") caption = "Four-eyes satisfied: you decided none of today's open cases.";
  else if (fourEyes.state === "unmet")
    caption = "Four-eyes not satisfied: you decided cases today, so another approver must sign off.";
  else caption = "Four-eyes applies to whoever signs off: an approver who decided none of today's open cases.";

  const eyes = fourEyes ? FOUR_EYES[fourEyes.state] : null;
  return (
    <Lead
      className={`so-lead so-lead-${state}`}
      aria-label="Release status"
      label="Release status"
      figure={RELEASE_LABELS[state]}
      caption={caption}
      foot={
        <>
          <StatusPill kind={met === day.length ? "done" : "late"}>
            {count(met)} of {count(day.length)} conditions met
          </StatusPill>
          {eyes && <StatusPill kind={eyes.kind}>{eyes.word}</StatusPill>}
        </>
      }
    />
  );
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
    const signedOffBy = day.data?.signed_off_by ?? null;
    const signedOff = release.data.signed_off || day.data?.status === "signed_off";
    body = (
      <>
        <ReleaseLead
          release={release.data}
          overview={overview.data}
          role={user.role}
          signedOff={signedOff}
          signedOffBy={signedOffBy}
        />
        <div className="so-grid">
          <div className="so-col so-col-main">
            <div className="so-area-conds">
              <Conditions release={release.data} overview={overview.data} role={user.role} signedOffBy={signedOffBy} />
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
      </>
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
