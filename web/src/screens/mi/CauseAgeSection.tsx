/**
 * Open breaks by cause and age: how many cases of each cause sit in each age bucket
 * (business days open), with each cause's gross and net NAV impact side by side (net
 * alone would let offsetting breaks hide each other). The impact per bucket is on demand.
 */
import type { Mi, MiBlock } from "../../api/types";
import { count, money, plural } from "../../format";
import { ageBucketLabel, causeLabel } from "../../vocabulary";
import { SectionHead } from "../../components/Paper";

type Grid = Mi["by_cause_age"];

function Count({ value }: { value: number }) {
  return <span className={value === 0 ? "faint" : undefined}>{count(value)}</span>;
}

function CountRow({ label, block, total = false }: { label: string; block: MiBlock; total?: boolean }) {
  return (
    <tr className={total ? "mi-total" : undefined}>
      <th scope="row">{label}</th>
      {block.cells.map((cell) => (
        <td key={cell.bucket} className="num">
          <Count value={cell.count} />
        </td>
      ))}
      <td className="num mi-strong">{count(block.count)}</td>
      <td className="num">{money(block.gross)}</td>
      <td className="num">{money(block.net, { signed: true })}</td>
    </tr>
  );
}

function ImpactRow({ label, block, total = false }: { label: string; block: MiBlock; total?: boolean }) {
  return (
    <tr className={total ? "mi-total" : undefined}>
      <th scope="row">{label}</th>
      {block.cells.flatMap((cell) => [
        <td key={`${cell.bucket}-g`} className="num">
          {cell.count ? money(cell.gross) : <span className="faint">{count(0)}</span>}
        </td>,
        <td key={`${cell.bucket}-n`} className="num">
          {cell.count ? money(cell.net, { signed: true }) : <span className="faint">{count(0)}</span>}
        </td>,
      ])}
    </tr>
  );
}

export function CauseAgeSection({ grid, currency }: { grid: Grid; currency: string }) {
  const { buckets, rows, total } = grid;
  return (
    <section className="mi-block" aria-labelledby="mi-h-cause">
      <SectionHead label="Open breaks" title="Open breaks by cause and age" id="mi-h-cause" />
      <p className="mi-sub">
        {total.count ? `${plural(total.count, "open case")}, age in business days` : "None open"}
      </p>
      {rows.length === 0 ? (
        <p className="card empty-state">No case is open at the end of the day.</p>
      ) : (
        <>
          <div className="card mi-card table-wrap">
            <table className="data-table mi-matrix">
              <caption className="sr-only">
                Open cases by cause and by business days open, with each cause&rsquo;s gross and net NAV impact in{" "}
                {currency}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Cause</th>
                  {buckets.map((b) => (
                    <th key={b} scope="col" className="num">
                      {ageBucketLabel(b)}
                    </th>
                  ))}
                  <th scope="col" className="num">
                    Total
                  </th>
                  <th scope="col" className="num">
                    Gross impact <span className="faint">{currency}</span>
                  </th>
                  <th scope="col" className="num">
                    Net impact <span className="faint">{currency}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <CountRow key={r.cause} label={causeLabel(r.cause)} block={r} />
                ))}
              </tbody>
              <tfoot>
                <CountRow label="All causes" block={total} total />
              </tfoot>
            </table>
          </div>
          <details className="mi-more">
            <summary>Show the impact by age</summary>
            <div className="card mi-card table-wrap">
              <table className="data-table mi-matrix">
                <caption className="sr-only">
                  Gross and net NAV impact in {currency} by cause and business days open
                </caption>
                <thead>
                  <tr>
                    <th scope="col" rowSpan={2}>
                      Cause
                    </th>
                    {buckets.map((b) => (
                      <th key={b} scope="colgroup" colSpan={2} className="mi-group">
                        {ageBucketLabel(b)}
                      </th>
                    ))}
                  </tr>
                  <tr>
                    {buckets.flatMap((b) => [
                      <th key={`${b}-g`} scope="col" className="num">
                        Gross
                      </th>,
                      <th key={`${b}-n`} scope="col" className="num">
                        Net
                      </th>,
                    ])}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <ImpactRow key={r.cause} label={causeLabel(r.cause)} block={r} />
                  ))}
                </tbody>
                <tfoot>
                  <ImpactRow label="All causes" block={total} total />
                </tfoot>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}
