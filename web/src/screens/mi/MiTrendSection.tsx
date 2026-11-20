/**
 * The trend: one thin bar per run day (oldest first, up to the day being viewed) for one
 * measure at a time (open, new, cleared, material, escalated or past SLA), each bar with
 * its figure above it and its day beneath, on a quiet scale with its top figure. The day
 * being viewed is the one bar in the accent. Every measure for every day, with the gross and
 * net impact and the average time to resolve, sits behind "Show the figures".
 */
import { useEffect, useRef, useState } from "react";

import type { MiTrendDay } from "../../api/types";
import { SectionHead } from "../../components/Paper";
import { count, dayLabel, dayShort, money, plural } from "../../format";
import { TREND_MEASURES, type TrendMeasure } from "../../vocabulary";

const MEASURES = Object.keys(TREND_MEASURES) as TrendMeasure[];

const HEIGHT = 112; // the bars' area
const TOP = 20; // room for a bar's figure above it
const LABEL = 22; // room for the day under each bar
const AXIS = 36; // room for the scale's figures on the left
const BAR = 12; // a thin bar
const SLOT = 40; // the least room per day; wider when the card allows

/** The width the chart has to fill, followed as the card resizes. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function Bars({
  trend,
  asOf,
  measure,
  room,
}: {
  trend: MiTrendDay[];
  asOf: string;
  measure: TrendMeasure;
  room: number;
}) {
  const max = Math.max(1, ...trend.map((d) => d[measure]));
  const slot = Math.max(SLOT, (room - AXIS) / Math.max(1, trend.length));
  const width = AXIS + trend.length * slot;
  const height = TOP + HEIGHT + LABEL;
  const base = TOP + HEIGHT;
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
      <g className="mi-axis">
        <line className="mi-grid-line" x1={AXIS} x2={width} y1={TOP + 4.5} y2={TOP + 4.5} />
        <text x={AXIS - 10} y={TOP + 8} textAnchor="end">
          {count(max)}
        </text>
        <line className="mi-chart-base" x1={AXIS} x2={width} y1={base - 0.5} y2={base - 0.5} />
        <text x={AXIS - 10} y={base + 3} textAnchor="end">
          0
        </text>
      </g>
      {trend.map((d, i) => {
        const value = d[measure];
        const h = value === 0 ? 0 : Math.max(3, (value / max) * (HEIGHT - 4));
        const mid = AXIS + i * slot + slot / 2;
        return (
          <g key={d.as_of} className={d.as_of === asOf ? "mi-bar current" : "mi-bar"}>
            <title>{`${dayLabel(d.as_of)}: ${plural(value, `${name} case`)}`}</title>
            {h > 0 && <rect x={mid - BAR / 2} y={base - 1 - h} width={BAR} height={h} rx={3} />}
            <text className="mi-bar-value" x={mid} y={base - 7 - h} textAnchor="middle">
              {count(value)}
            </text>
            <text className="mi-bar-day" x={mid} y={base + LABEL - 5} textAnchor="middle">
              {dayShort(d.as_of)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function MiTrendSection({ trend, asOf, currency }: { trend: MiTrendDay[]; asOf: string; currency: string }) {
  const [measure, setMeasure] = useState<TrendMeasure>("open_cases");
  const [chartRef, room] = useWidth();
  const first = trend[0];
  const last = trend[trend.length - 1];
  return (
    <section className="mi-block" aria-labelledby="mi-h-trend">
      <SectionHead label="Run days" title="Trend" id="mi-h-trend" />
      <p className="mi-sub">
        {first && last
          ? first === last
            ? `${dayLabel(first.as_of)}, the only run day so far`
            : `${plural(trend.length, "run day")}, ${dayShort(first.as_of)} to ${dayShort(last.as_of)}`
          : "no run day yet"}
      </p>
      {trend.length === 0 ? (
        <p className="card empty-state">No day of this fund has been run yet.</p>
      ) : (
        <>
          <div className="card mi-chart-card">
            <div className="seg mi-measures" role="group" aria-label="Measure shown in the chart">
              {MEASURES.map((m) => (
                <button key={m} type="button" aria-pressed={m === measure} onClick={() => setMeasure(m)}>
                  {TREND_MEASURES[m]}
                </button>
              ))}
            </div>
            <div className="mi-chart-wrap" ref={chartRef}>
              <Bars trend={trend} asOf={asOf} measure={measure} room={room} />
            </div>
          </div>
          <details className="mi-more">
            <summary>Show the figures</summary>
            <div className="card mi-card table-wrap">
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
