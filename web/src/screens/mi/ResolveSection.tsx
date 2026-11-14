/**
 * Time to resolve: for each cause, how many cases have cleared up to the day and how many
 * business days they were open on average. A case's cause is the one it cleared as.
 */
import type { Mi } from "../../api/types";
import { count, money, plural } from "../../format";
import { causeLabel } from "../../vocabulary";

export function ResolveSection({ resolve }: { resolve: Mi["time_to_resolve"] }) {
  const { rows, all } = resolve;
  return (
    <section className="mi-block" aria-labelledby="mi-h-resolve">
      <div className="mi-block-head">
        <h2 id="mi-h-resolve">Time to resolve</h2>
        <span className="faint">{all.cleared ? `${plural(all.cleared, "case")} cleared so far` : "nothing cleared yet"}</span>
      </div>
      {rows.length === 0 ? (
        <p className="mi-note muted">No case has cleared yet, so there is no time to resolve.</p>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <caption className="sr-only">Cases cleared and their average business days open, by cause</caption>
            <thead>
              <tr>
                <th scope="col">Cause</th>
                <th scope="col" className="num">
                  Cleared
                </th>
                <th scope="col" className="num">
                  Average business days
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.cause}>
                  <th scope="row">{causeLabel(r.cause)}</th>
                  <td className="num">{count(r.cleared)}</td>
                  <td className="num">{money(r.avg_days)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="mi-total">
                <th scope="row">All causes</th>
                <td className="num">{count(all.cleared)}</td>
                <td className="num mi-strong">{money(all.avg_days)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </section>
  );
}
