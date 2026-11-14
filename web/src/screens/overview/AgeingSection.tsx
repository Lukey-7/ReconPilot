/**
 * The open cases by age (business days open), always all three buckets, with the gross
 * and net NAV impact of each bucket side by side. A bucket opens the case queue filtered
 * to that age.
 */
import { Link } from "react-router";

import type { AgeingBucket } from "../../api/types";
import { count, money } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { ageBucketLabel } from "../../vocabulary";

export function AgeingSection({ ageing, currency }: { ageing: AgeingBucket[]; currency: string }) {
  const { href } = useWorkspace();
  const total = ageing.reduce((sum, b) => sum + b.count, 0);
  return (
    <section className="ov-block ov-ageing" aria-labelledby="ov-h-ageing">
      <div className="ov-block-head">
        <h2 id="ov-h-ageing">Ageing</h2>
        <span className="faint">business days open</span>
      </div>
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
                  {b.count > 0 ? <Link to={href("/cases", { age: b.bucket })}>{ageBucketLabel(b.bucket)}</Link> : ageBucketLabel(b.bucket)}                </th>
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
