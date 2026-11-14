/**
 * The day's files, one row per file the engine reads: held or missing, its size and who
 * uploaded it, and what the server's validation found in it. Then the problems by file and
 * row: errors first and in full (they block the run), warnings on demand.
 */
import type { Day, ExpectedFile, ValidationIssue, ValidationReport } from "../../api/types";
import { Icon } from "../../components/Icon";
import { count, dayLabel, plural, timestamp } from "../../format";

export function sizeText(bytes: number): string {
  if (bytes < 1024) return `${count(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toLocaleString("en-GB", { maximumFractionDigits: 1 })} KB`;
  return `${(bytes / 1024 / 1024).toLocaleString("en-GB", { maximumFractionDigits: 1 })} MB`;
}

/** When a file came in: the time alone for today, the date and time otherwise. */
function uploadedWhen(iso: string | null): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const today = new Date();
  if (at.toDateString() !== today.toDateString()) return timestamp(iso);
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" }).format(at);
}

function issueWhere(issue: ValidationIssue): string {
  return issue.row != null ? `${issue.file}, row ${count(issue.row)}` : issue.file;
}

/** Issues in file order (the engine's order of files), then by row; whole-file issues first. */
function byFileAndRow(issues: ValidationIssue[], order: string[]): ValidationIssue[] {
  const rank = (file: string) => {
    const i = order.indexOf(file);
    return i === -1 ? order.length : i;
  };
  return issues
    .map((issue, index) => ({ issue, index }))
    .sort(
      (a, b) =>
        rank(a.issue.file) - rank(b.issue.file) ||
        a.issue.file.localeCompare(b.issue.file) ||
        (a.issue.row ?? 0) - (b.issue.row ?? 0) ||
        a.index - b.index,
    )
    .map(({ issue }) => issue);
}

function IssueList({ issues }: { issues: ValidationIssue[] }) {
  return (
    <ul className="up-issues">
      {issues.map((issue, i) => (
        <li key={`${issue.file}-${issue.row ?? "file"}-${i}`}>
          <span className="up-issue-where mono">{issueWhere(issue)}</span>
          <span>{issue.message}</span>
        </li>
      ))}
    </ul>
  );
}

interface Row {
  filename: string;
  required: boolean | null;
  held: Day["files"][number] | null;
  errors: number;
  warnings: number;
}

function rowsFor(day: Day | undefined, expected: ExpectedFile[] | null, report: ValidationReport | null): Row[] {
  const held = new Map((day?.files ?? []).map((f) => [f.filename.toLowerCase(), f]));
  const errors = new Map<string, number>();
  const warnings = new Map<string, number>();
  for (const e of report?.errors ?? []) errors.set(e.file.toLowerCase(), (errors.get(e.file.toLowerCase()) ?? 0) + 1);
  for (const w of report?.warnings ?? [])
    warnings.set(w.file.toLowerCase(), (warnings.get(w.file.toLowerCase()) ?? 0) + 1);
  const make = (filename: string, required: boolean | null): Row => {
    const key = filename.toLowerCase();
    return { filename, required, held: held.get(key) ?? null, errors: errors.get(key) ?? 0, warnings: warnings.get(key) ?? 0 };
  };
  if (expected) return expected.map((f) => make(f.filename, f.required));
  // Without the list of expected files, show the files the day holds.
  return (day?.files ?? []).map((f) => make(f.filename, null));
}

function Result({ row, checked }: { row: Row; checked: boolean }) {
  if (!row.held) {
    if (row.required === false) return <span className="faint">Not uploaded (optional)</span>;
    return (
      <span className="up-res up-res-bad">
        <Icon name="cross" /> Missing{row.required ? ", needed for the run" : ""}
      </span>
    );
  }
  if (!checked) return <span className="faint">Not checked yet</span>;
  if (row.errors) {
    return (
      <span className="up-res up-res-bad">
        <Icon name="cross" /> {plural(row.errors, "error")}
        {row.warnings ? `, ${plural(row.warnings, "warning")}` : ""}
      </span>
    );
  }
  return (
    <span className="up-res up-res-ok">
      <Icon name="check" /> Valid{row.warnings ? `, ${plural(row.warnings, "warning")}` : ""}
    </span>
  );
}

export function FileChecklist({
  asOf,
  day,
  expected,
}: {
  asOf: string;
  day: Day | undefined;
  expected: ExpectedFile[] | null;
}) {
  const report = day?.validation ?? null;
  const rows = rowsFor(day, expected, report);
  if (!rows.length) return null;
  return (
    <div className="table-wrap">
      <table className="data-table up-files">
        <caption>Files held for {dayLabel(asOf)}, and what the checks found</caption>
        <thead>
          <tr>
            <th scope="col">File</th>
            <th scope="col" className="num">
              Size
            </th>
            <th scope="col">Uploaded</th>
            <th scope="col">Check</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filename} className={row.held ? undefined : "up-missing"}>
              <th scope="row">
                <span className="mono">{row.filename}</span>
                {row.required === false && <span className="up-optional">optional</span>}
              </th>
              <td className="num">{row.held ? sizeText(row.held.size_bytes) : ""}</td>
              <td>
                {row.held
                  ? `${row.held.uploaded_by ?? "unknown"}${row.held.uploaded_at ? `, ${uploadedWhen(row.held.uploaded_at)}` : ""}`
                  : ""}
              </td>
              <td>
                <Result row={row} checked={!!report} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {day && day.files.length > 0 && (
        <details className="up-hashes">
          <summary>SHA-256 fingerprints of the files held</summary>
          <ul>
            {day.files.map((f) => (
              <li key={f.kind}>
                {f.filename}: <span className="mono">{f.sha256}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** The validation's verdict, then every error by file and row, and the warnings on demand. */
export function Validation({ day, expected }: { day: Day; expected: ExpectedFile[] | null }) {
  const report = day.validation;
  if (!report) return null;
  const order = (expected ?? []).map((f) => f.filename);
  const errors = byFileAndRow(report.errors, order);
  const warnings = byFileAndRow(report.warnings, order);
  return (
    <div className="up-validation" aria-live="polite">
      {errors.length > 0 ? (
        <div className="up-errors" role="alert">
          <p className="up-verdict">
            <Icon name="cross" />
            {plural(errors.length, "problem")} {errors.length === 1 ? "blocks" : "block"} the run. Correct the files and
            upload them again.
          </p>
          <IssueList issues={errors} />
        </div>
      ) : (
        <p className="up-verdict up-ok">
          <Icon name="check" />
          The files are valid{warnings.length ? ", with warnings that do not block the run" : ""}.
        </p>
      )}
      {warnings.length > 0 && (
        <details className="up-warnings">
          <summary>{plural(warnings.length, "warning")}</summary>
          <IssueList issues={warnings} />
        </details>
      )}
    </div>
  );
}
