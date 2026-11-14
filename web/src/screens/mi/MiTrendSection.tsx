/**
 * The trend: one bar per run day (oldest first, up to the day being viewed) for one
 * measure at a time (open, new, cleared, material, escalated or past SLA), each bar with
 * its figure and day written beside it. Every measure for every day, with the gross and
 * net impact and the average time to resolve, sits behind "Show the figures".
 */
import { useState } from "react";

import type { MiTrendDay } from "../../api/types";
import { count, dayLabel, dayShort, money, plural } from "../../format";
import { TREND_MEASURES, type TrendMeasure } from "../../vocabulary";

const MEASURES = Object.keys(TREND_MEASURES) as TrendMeasure[];

const HEIGHT = 96; // the bars' area
const TOP = 16; // room for a bar's figure above it
const LABEL = 18; // room for the day under each bar
const BAR = 22;
const GAP = 12;

function Bars({ trend, asOf, measure }: { trend: MiTrendDay[]; asOf: string; measure: TrendMeasure }) {
  const max = Math.max(1, ...trend.map((d) => d[measure]));
  const width = trend.length * (BAR + GAP) - GAP;
  const height = TOP + HEIGHT + LABEL;
  const name = TREND_MEASURES[measure].toLowerCase();
  return (
    <svg
      className="mi-chart"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`${TREND_MEASURES[measure]} cases per run day, ${dayShort(trend[0]?.as_of)} to ${dayShort(
        trend[trend.length - 1]?.as_of,
      )}`}
    >
      <line className="mi-chart-base" x1={0} x2={width} y1={TOP + HEIGHT - 0.5} y2={TOP + HEIGHT - 0.5} />
      {trend.map((d, i) => {
        const value = d[measure];
        const h = value === 0 ? 0 : Math.max(3, (value / max) * (HEIGHT - 4));
        const x = i * (BAR + GAP);
        return (
          <g key={d.as_of} className={d.as_of === asOf ? "mi-bar current" : "mi-bar"}>
            <title>{`${dayLabel(d.as_of)}: ${plural(value, `${name} case`)}`}</title>
            {h > 0 && <rect x={x} y={TOP + HEIGHT - 1 - h} width={BAR} height={h} rx={2} />}
            <text className="mi-bar-value" x={x + BAR / 2} y={TOP + HEIGHT - 5 - h} textAnchor="middle">
              {count(value)}
            </text>
            <text className="mi-bar-day" x={x + BAR / 2} y={TOP + HEIGHT + LABEL - 4} textAnchor="middle">
              {dayShort(d.as_of).split(" ")[0]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function MiTrendSection({ trend, asOf, currency }: { trend: MiTrendDay[]; asOf: string; currency: string }) {
  const [measure, setMeasure] = useState<TrendMeasure>("open_cases");
  const first = trend[0];
  const last = trend[trend.length - 1];
  return (
    <section className="mi-block" aria-labelledby="mi-h-trend">
      <div className="mi-block-head">
        <h2 id="mi-h-trend">Trend</h2>
        <span className="faint">
          {first && last
            ? first === last
              ? `${dayLabel(first.as_of)}, the only run day so far`
              : `${plural(trend.length, "run day")}, ${dayShort(first.as_of)} to ${dayShort(last.as_of)}`
            : "no run day yet"}
        </span>
      </div>
      {trend.length === 0 ? (
        <p className="mi-note muted">No day of this fund has been run yet.</p>
      ) : (
        <>
          <div className="mi-measures" role="group" aria-label="Measure shown in the chart">
            {MEASURES.map((m) => (
              <button
                key={m}
                type="button"
                className={m === measure ? "btn mi-measure active" : "btn ghost mi-measure"}
                aria-pressed={m === measure}
                onClick={() => setMeasure(m)}
              >
                {TREND_MEASURES[m]}
              </button>
            ))}
          </div>
          <div className="mi-chart-wrap">
            <Bars trend={trend} asOf={asOf} measure={measure} />
          </div>
          <details className="mi-more">
            <summary>Show the figures</summary>
            <div className="table-wrap">
              <table className="data-table mi-trend-table">
                <caption className="sr-only">Cases and NAV impact in {currency} per run day, oldest first</caption>
                <thead>
                  <tr>
                    <th scope="col">Day</th>
                    {MEASURES.map((m) => (
                      <th key={m} scope="col" className="num">
                        {TREND_MEASURES[m]}
                      </th>
                    ))}
                    <th scope="col" className="num">
                      Over 5 days
                    </th>
                    <th scope="col" className="num">
                      Gross impact
                    </th>
                    <th scope="col" className="num">
                      Net impact
                    </th>
                    <th scope="col" className="num">
                      Days to resolve
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {trend.map((d) => (
                    <tr key={d.as_of} aria-current={d.as_of === asOf ? "date" : undefined}>
                      <th scope="row">{dayLabel(d.as_of)}</th>
                      {MEASURES.map((m) => (
                        <td key={m} className="num">
                          {count(d[m])}
                        </td>
                      ))}
                      <td className="num">{count(d.aged_over_5)}</td>
                      <td className="num">{money(d.open_gross_impact)}</td>
                      <td className="num">{money(d.open_nav_impact, { signed: true })}</td>
                      <td className="num">{money(d.avg_days_to_resolve)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mi-note faint">
              Open, material, escalated, past SLA and over 5 days count the cases open at the end of each day. Days to
              resolve is the average business days open of every case cleared up to that day.
            </p>
          </details>
        </>
      )}
    </section>
  );
}
