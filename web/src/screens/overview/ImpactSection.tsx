/**
 * Open breaks ranked by NAV impact, largest first, as one card of hairline rows. The totals
 * (net with gross, never net alone) are the tiles under the lead card; each case's own gross
 * exposure is in the workbench. The ten largest show at first; the rest are a click away.
 * A row opens its case in the workbench.
 */
import { createColumnHelper } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import type { Overview, OverviewCase } from "../../api/types";
import { DataTable } from "../../components/DataTable";
import { StatusLabel } from "../../components/Labels";
import { bp, count, money, plural } from "../../format";
import { FLAGS } from "../../vocabulary";
import { CaseLink, currentCause, securityText, useCaseHref } from "./caseLinks";
import { OvHead } from "./OvHead";

/** How many open breaks show before "Show all". */
export const IMPACT_ROWS_SHOWN = 10;

type Impact = NonNullable<Overview["impact"]>;

function Flags({ c }: { c: OverviewCase }) {
  const flags: string[] = [];
  if (c.material) flags.push(FLAGS.material);
  if (c.escalated) flags.push(FLAGS.escalated);
  if (c.sla_breached) flags.push(FLAGS.sla);
  if (!flags.length && !c.ai_flag) return null;
  return (
    <span className="ov-flags">
      {flags.map((f) => (
        <span key={f} className="tag">
          {f}
        </span>
      ))}
      {c.ai_flag && <span className="status info ov-flag-ai">{FLAGS.ai}</span>}
    </span>
  );
}

/**
 * A thin bar for the size of the impact, brighter when material, with a tick at the
 * materiality threshold. Decorative: the figure beside it and the Material label say it.
 */
function ImpactBar({ value, scale, threshold, material }: { value: number; scale: number; threshold: number; material: boolean }) {
  const width = scale > 0 ? Math.min(100, (Math.abs(value) / scale) * 100) : 0;
  const tick = scale > 0 ? Math.min(100, (threshold / scale) * 100) : 0;
  return (
    <span className="ov-bar" aria-hidden="true">
      <span className={`ov-bar-fill ${material ? "material" : ""}`.trim()} style={{ width: `${width.toFixed(2)}%` }} />
      {threshold > 0 && <span className="ov-bar-tick" style={{ left: `${tick.toFixed(2)}%` }} />}
    </span>
  );
}

const helper = createColumnHelper<OverviewCase>();

export function ImpactSection({ impact, currency, materialityBp }: { impact: Impact; currency: string; materialityBp: number }) {
  const navigate = useNavigate();
  const caseHref = useCaseHref();
  const [showAll, setShowAll] = useState(false);
  const cases = impact.cases;
  const rows = showAll ? cases : cases.slice(0, IMPACT_ROWS_SHOWN);

  const columns = useMemo(() => {
    const scale = Math.max(materialityBp, ...cases.map((c) => Math.abs(c.nav_impact_bp))) * 1.05;
    return [
      helper.accessor("case_id", {
        header: "Case",
        cell: (ctx) => (
          <span className="ov-case-cell">
            <CaseLink caseId={ctx.getValue()} />
            <span className="faint ov-sec">{securityText(ctx.row.original)}</span>
          </span>
        ),
        enableSorting: false,
      }),
      helper.accessor((c) => currentCause(c), {
        id: "cause",
        header: "Cause",
        cell: (ctx) => (
          <span className="ov-cause-cell">
            <span>{ctx.getValue()}</span>
            <Flags c={ctx.row.original} />
          </span>
        ),
        enableSorting: false,
      }),
      helper.accessor((c) => Math.abs(c.nav_impact_bp), {
        id: "bp",
        header: () => (
          <>
            <span className="sr-only">NAV impact, </span>bp
          </>
        ),
        cell: (ctx) => (
          <span className="ov-bp-cell">
            <ImpactBar
              value={ctx.row.original.nav_impact_bp}
              scale={scale}
              threshold={materialityBp}
              material={ctx.row.original.material}
            />
            <span className="fig">{bp(ctx.row.original.nav_impact_bp)}</span>
          </span>
        ),
        meta: { numeric: true },
        enableSorting: false,
      }),
      helper.accessor("nav_impact", {
        header: () => (
          <>
            <span className="sr-only">NAV impact, </span>
            {currency}
          </>
        ),
        cell: (ctx) => money(ctx.getValue(), { signed: true }),
        meta: { numeric: true },
        enableSorting: false,
      }),
      helper.accessor("age_days", {
        header: () => (
          <>
            Age<span className="sr-only">, business days</span>
          </>
        ),
        cell: (ctx) => count(ctx.getValue()),
        meta: { numeric: true },
        enableSorting: false,
      }),
      helper.accessor("status", {
        header: "Status",
        cell: (ctx) => <StatusLabel status={ctx.getValue()} />,
        enableSorting: false,
      }),
    ];
  }, [cases, currency, materialityBp]);

  return (
    <section className="ov-impact" aria-labelledby="ov-h-impact">
      <OvHead label="Open breaks" id="ov-h-impact" title="Open breaks by NAV impact">
        {cases.length ? `${plural(cases.length, "open case")}, largest first` : "None open"}
      </OvHead>
      <div className="card ov-table-card">
        <DataTable
          data={rows}
          columns={columns}
          caption="Open cases ranked by the size of their NAV impact. Gross adds every impact as a positive amount; net lets gains and losses offset."
          captionHidden
          getRowId={(c) => c.case_id}
          onActivate={(c) => navigate(caseHref(c.case_id))}
          empty="No open breaks. Every case from earlier days has cleared or there were none."
          className="ov-impact-table list-enter"
        />
        {cases.length > IMPACT_ROWS_SHOWN && (
          <div className="ov-show-all">
            <button type="button" className="btn quiet" aria-expanded={showAll} onClick={() => setShowAll((v) => !v)}>
              {showAll ? `Show the ${IMPACT_ROWS_SHOWN} largest` : `Show all ${plural(cases.length, "open case")}`}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
