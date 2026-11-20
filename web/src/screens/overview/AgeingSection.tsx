/**
 * The open cases by age (business days open), always all three buckets, with the gross
 * and net NAV impact of each bucket side by side. Each bucket carries a calm 6px track
 * filling with its share of the open cases: grey, and muted red for cases open over five
 * business days (escalated as aged). A bucket opens the case queue filtered to that age.
 */
import { Link } from "react-router";

import type { AgeingBucket } from "../../api/types";
import { Track } from "../../components/Paper";
import { count, money } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { ageBucketLabel } from "../../vocabulary";
import { OvHead } from "./OvHead";

/** Cases open over five business days are escalated as aged: their track is drawn as late. */
const AGED = ">5";

export function AgeingSection({ ageing, currency }: { ageing: AgeingBucket[]; currency: string }) {
  const { href } = useWorkspace();
  const total = ageing.reduce((sum, b) => sum + b.count, 0);
  return (
    <section className="ov-block ov-ageing" aria-labelledby="ov-h-ageing">
      <OvHead label="Open cases" id="ov-h-ageing" title="Ageing">
        business days open
      </OvHead>
      <div className="table-wrap">
        <table className="data-table ov-ageing-table">
          <caption className="sr-only">Open cases by business days open, with their gross and net NAV impact in {currency}</caption>
          <thead>
            <tr>
              <th scope="col">Open for</th>
              <th scope="col" className="num">
                Cases
              </th>
              <th scope="col" className="num">
                Gross<span className="sr-only">, {currency}</span>
              </th>
              <th scope="col" className="num">
                Net<span className="sr-only">, {currency}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {ageing.map((b) => (
              <tr key={b.bucket} data-bucket={b.bucket}>
                <th scope="row" className="ov-age-name">
                  {b.count > 0 ? (
                    <Link to={href("/cases", { age: b.bucket })}>{ageBucketLabel(b.bucket)}</Link>
                  ) : (
                    ageBucketLabel(b.bucket)
                  )}
                  <Track value={b.count} max={total} tone={b.bucket === AGED && b.count > 0 ? "late" : "ok"} />
                </th>
                <td className="num">{count(b.count)}</td>
                <td className="num">{money(b.gross)}</td>
                <td className="num">{money(b.net, { signed: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total === 0 && <p className="ov-note muted">No case is open.</p>}
    </section>
  );
}
