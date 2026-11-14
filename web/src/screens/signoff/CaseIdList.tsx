/** Case ids that open the case in the workbench; past a handful, the rest wait behind "Show all". */
import { plural } from "../../format";
import { CaseLink } from "../overview/caseLinks";

export const CASES_SHOWN = 6;

export function CaseIdList({ ids, label = "Cases" }: { ids: string[]; label?: string }) {
  if (!ids.length) return null;
  const shown = ids.slice(0, CASES_SHOWN);
  const rest = ids.slice(CASES_SHOWN);
  return (
    <div className="so-cases">
      <ul aria-label={label}>
        {shown.map((id) => (
          <li key={id}>
            <CaseLink caseId={id} />
          </li>
        ))}
      </ul>
      {rest.length > 0 && (
        <details className="so-more">
          <summary>Show all {plural(ids.length, "case")}</summary>
          <ul aria-label={`More ${label.toLowerCase()}`}>
            {rest.map((id) => (
              <li key={id}>
                <CaseLink caseId={id} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
