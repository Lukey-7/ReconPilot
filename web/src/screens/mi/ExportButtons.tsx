/**
 * The day's two exports: the exception report (the engine's Excel workbook, MI sheet
 * included) and the MI data in tidy CSV for a BI tool. Each download is recorded in the
 * audit log by the server. A refusal is shown in the server's words; a finished download
 * is announced, so a screen reader hears that the file was saved.
 */
import { type ExportKind, useExport } from "../../api/queries";
import { ErrorLine } from "../../components/QueryState";
import { useCommand } from "../../keyboard/KeyboardProvider";
import { EXPORTS, EXPORT_FORMATS } from "../../vocabulary";

const KINDS: ExportKind[] = ["report", "mi_csv"];

export function ExportButtons({ fund, asOf }: { fund: string; asOf: string }) {
  const exporting = useExport(fund, asOf);
  const busy = exporting.isPending ? exporting.variables : null;
  const options = { group: "MI", enabled: !exporting.isPending, keywords: "export download" };
  useCommand(`Download the ${EXPORTS.report.toLowerCase()} (${EXPORT_FORMATS.report})`, () => exporting.mutate("report"), options);
  useCommand(`Download the ${EXPORTS.mi_csv} (${EXPORT_FORMATS.mi_csv})`, () => exporting.mutate("mi_csv"), options);
  return (
    <div className="mi-exports">
      <div className="mi-export-buttons" role="group" aria-label="Exports for this day">
        {KINDS.map((kind) => (
          <button
            key={kind}
            type="button"
            className="btn quiet"
            disabled={exporting.isPending}
            aria-busy={busy === kind}
            onClick={() => exporting.mutate(kind)}
          >
            {busy === kind ? "Preparing…" : EXPORTS[kind]}
            <span className="mi-export-format">{EXPORT_FORMATS[kind]}</span>
          </button>
        ))}
      </div>
      <p className="mi-export-status faint" role="status">
        {exporting.isSuccess ? `Downloaded ${exporting.data.filename}.` : ""}
      </p>
      {exporting.isError && <ErrorLine error={exporting.error} />}
    </div>
  );
}
