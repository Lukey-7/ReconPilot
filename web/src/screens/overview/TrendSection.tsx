/**
 * A small trend: open cases at the end of each run day (oldest first, up to the day being
 * viewed), as thin bars with the day being viewed picked out. Each bar names its day and
 * figures on hover; the figures for every day sit behind "Show the figures", with the open
 * impact gross beside net (never net alone), and each earlier day opens that day's overview.
 */
import { Link } from "react-router";

import type { TrendDay } from "../../api/types";
import { count, dayLabel, dayShort, money, plural } from "../../format";
import { useWorkspace } from "../../shell/workspace";

const HEIGHT = 56;
const BAR = 14;
const GAP = 6;

function barTitle(d: TrendDay): string {
  return `${dayLabel(d.as_of)}: ${plural(d.open_cases, "open case")}, ${count(d.new_cases)} new, ${count(d.cleared_cases)} cleared`;
}

function Bars({ trend, asOf }: { trend: TrendDay[]; asOf: string }) {
  const max = Math.max(1, ...trend.map((d) => d.open_cases));
  const width = trend.length * (BAR + GAP) - GAP;
  return (
    <svg
      className="ov-trend-chart"
      viewBox={`0 0 ${width} ${HEIGHT}`}
      width={width}
      height={HEIGHT}
      role="img"
      aria-label={`Open cases per run day, ${dayShort(trend[0]?.as_of)} to ${dayShort(trend[trend.length - 1]?.as_of)}`}
    >
      <line className="ov-trend-base" x1={0} x2={width} y1={HEIGHT - 0.5} y2={HEIGHT - 0.5} />
      {trend.map((d, i) => {
        const h = d.open_cases === 0 ? 0 : Math.max(3, (d.open_cases / max) * (HEIGHT - 4));
        const x = i * (BAR + GAP);
        return (
          <g key={d.as_of} className={d.as_of === asOf ? "ov-trend-bar current" : "ov-trend-bar"}>
            <title>{barTitle(d)}</title>
            {/* A hit target the full height of the chart, wider than the mark. */}
            <rect className="ov-trend-hit" x={x - GAP / 2} y={0} width={BAR + GAP} height={HEIGHT} />
            {h > 0 && <rect x={x} y={HEIGHT - 1 - h} width={BAR} height={h} rx={2} />}
          </g>
        );
      })}
    </svg>
  );
}

export function TrendSection({ trend, asOf, currency }: { trend: TrendDay[]; asOf: string; currency: string }) {
  const { href } = useWorkspace();
  const last = trend[trend.length - 1];
  const previous = trend[trend.length - 2];
  let headline: string | null = null;
  if (last && previous) {
    const change = last.open_cases - previous.open_cases;
    headline =
      change === 0
        ? `Open cases unchanged at ${count(last.open_cases)} since ${dayShort(previous.as_of)}.`
        : `Open cases ${change > 0 ? "up" : "down"} ${count(Math.abs(change))} since ${dayShort(previous.as_of)}, to ${count(last.open_cases)}.`;
  } else if (last) {
    headline = `${plural(last.open_cases, "open case")} on the first run day.`;
  }

  return (
    <section className="ov-block ov-trend" aria-labelledby="ov-h-trend">
      <div className="ov-block-head">
        <h2 id="ov-h-trend">Trend</h2>
        <span className="faint">open cases per run day</span>
      </div>
      {trend.length === 0 ? (
        <p className="ov-note muted">No day of this fund has been run yet.</p>
      ) : (
        <>
          {headline && <p className="ov-note">{headline}</p>}
          <Bars trend={trend} asOf={asOf} />
          <details className="ov-more-block">
            <summary>Show the figures</summary>
            <div className="table-wrap">
              <table className="data-table ov-trend-table">
                <caption className="sr-only">Cases and open NAV impact in {currency} per run day, oldest first</caption>
                <thead>
                  <tr>
                    <th scope="col">Day</th>
                    <th scope="col" className="num">
                      Open
                    </th>
                    <th scope="col" className="num">
                      New
                    </th>
                    <th scope="col" className="num">
                      Cleared
                    </th>
                    <th scope="col" className="num">
                      Past SLA
                    </th>
                    <th scope="col" className="num">
                      Material
                    </th>
                    <th scope="col" className="num">
                      Gross impact
                    </th>
                    <th scope="col" className="num">
                      Net impact
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {trend.map((d) => (
                    <tr key={d.as_of} aria-current={d.as_of === asOf ? "date" : undefined}>
                      <th scope="row">
                        {d.as_of === asOf ? (
                          dayLabel(d.as_of)
                        ) : (
                          <Link to={href("/overview", { day: d.as_of })} title={`Open the overview for ${dayLabel(d.as_of)}`}>
                            {dayLabel(d.as_of)}
                          </Link>
                        )}
                      </th>
                      <td className="num">{count(d.open_cases)}</td>
                      <td className="num">{count(d.new_cases)}</td>
                      <td className="num">{count(d.cleared_cases)}</td>
                      <td className="num">{count(d.sla_breaches_open)}</td>
                      <td className="num">{count(d.material_open)}</td>
                      <td className="num">{money(d.open_gross_impact)}</td>
                      <td className="num">{money(d.open_nav_impact, { signed: true })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}
