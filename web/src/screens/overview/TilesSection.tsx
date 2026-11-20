/**
 * The overview's secondary figures as four tiles under the lead card: net impact (with gross
 * beneath it, never net alone, so offsetting breaks cannot hide each other), how many open
 * cases are material, how many cases are open, and the oldest open break. Every figure is
 * the server's; the oldest break is the largest age among the open cases it sent.
 */
import type { ReactNode } from "react";

import type { Overview } from "../../api/types";
import { TweenedMoney } from "../../components/Figures";
import { bp, count, plural } from "../../format";
import { CaseLink } from "./caseLinks";

type Impact = NonNullable<Overview["impact"]>;
type Accounted = NonNullable<Overview["accounted"]>;

/** One tile as a term and its figures: label, figure (one line), then a note. */
function Tile({ label, figure, note, testId }: { label: string; figure: ReactNode; note?: ReactNode; testId?: string }) {
  return (
    <div className="tile">
      <dt className="tile-label">{label}</dt>
      <dd className="tile-figure" data-testid={testId}>
        {figure}
      </dd>
      {note != null && <dd className="tile-note">{note}</dd>}
    </div>
  );
}

export function TilesSection({
  impact,
  accounted,
  currency,
  materialityBp,
}: {
  impact: Impact;
  accounted: Accounted;
  currency: string;
  materialityBp: number;
}) {
  const oldest = impact.cases.reduce<Impact["cases"][number] | null>(
    (best, c) => (best == null || c.age_days > best.age_days ? c : best),
    null,
  );
  return (
    <section className="ov-tiles" aria-label="NAV impact of the open cases">
      <dl className="tiles tiles-4">
        <Tile
          label="Net impact"
          testId="impact-net"
          figure={
            <>
              <TweenedMoney value={impact.net} signed /> <span className="ov-unit">{currency}</span>
            </>
          }
          note={
            <span data-testid="impact-gross">
              Gross{" "}
              <span className="fig">
                <TweenedMoney value={impact.gross} />
              </span>{" "}
              {currency}
            </span>
          }
        />
        <Tile
          label="Material"
          figure={count(impact.material)}
          note={`at ${bp(materialityBp).replace(/^\+/, "")} or more`}
        />
        <Tile label="Open cases" figure={count(accounted.open_cases)} note={`${count(accounted.pending)} pending a decision`} />
        <Tile
          label="Oldest break"
          figure={oldest ? plural(oldest.age_days, "business day") : "None open"}
          note={oldest ? <CaseLink caseId={oldest.case_id} /> : "No case is open."}
        />
      </dl>
    </section>
  );
}
