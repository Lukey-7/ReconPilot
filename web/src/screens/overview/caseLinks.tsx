/**
 * Links from the overview into the case workbench, keeping the fund and day:
 * `/cases?fund=GEF1&day=2026-11-10&case=C1` (phase 2 plan, stage 2b).
 */
import { useCallback } from "react";
import { Link } from "react-router";

import { useWorkspace } from "../../shell/workspace";
import { causeLabel } from "../../vocabulary";

/** The workbench address for one case. */
export function useCaseHref(): (caseId: string) => string {
  const { href } = useWorkspace();
  return useCallback((caseId: string) => href("/cases", { case: caseId }), [href]);
}

/**
 * A case id that opens the case. It stops the click from reaching an activatable table
 * row around it, so one click opens the case once.
 */
export function CaseLink({ caseId }: { caseId: string }) {
  const caseHref = useCaseHref();
  return (
    <Link className="ov-case" to={caseHref(caseId)} onClick={(event) => event.stopPropagation()}>
      {caseId}
    </Link>
  );
}

/** The cause a case shows now: the reclassified cause if a person changed it, otherwise the engine's. */
export function currentCause(c: { category: string; final_category: string | null }): string {
  return causeLabel(c.final_category ?? c.category);
}

/** The security's name, else its id, else "Custodian cash line" (a cash break has no security). */
export function securityText(c: { security_id: string; security_name: string }): string {
  return c.security_name || c.security_id || "Custodian cash line";
}
