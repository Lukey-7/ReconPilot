/**
 * The day's two exports: the exception report (the engine's Excel workbook, MI sheet
 * included) and the MI data in tidy CSV for a BI tool. Each download is recorded in the
 * audit log by the server. A refusal is shown in the server's words; a finished download
 * is announced, so a screen reader hears that the file was saved.
 */
import { type ExportKind, useExport } from "../../api/queries";
import { ErrorLine } from "../../components/QueryState";
import { EXPORTS, EXPORT_FORMATS } from "../../vocabulary";

const KINDS: ExportKind[] = ["report", "mi_csv"];

export function ExportButtons({ fund, asOf }: { fund: string; asOf: string }) {
  const exporting = useExport(fund, asOf);
  const busy = exporting.isPending ? exporting.variables : null;
  return (
    <div className="mi-exports">
      <div className="mi-export-buttons" role="group" aria-label="Exports for this day">
        {KINDS.map((kind) => (
          <button
            key={kind}
            type="button"
            className="btn"
            disabled={exporting.isPending}
            aria-busy={busy === kind}
            onClick={() => exporting.mutate(kind)}
          >
            {busy === kind ? "Preparing…" : EXPORTS[kind]}
            <span className="faint">{EXPORT_FORMATS[kind]}</span>
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
