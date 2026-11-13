/** The line under a screen's title: which fund and which business day it shows. */
import { dayLabel } from "../format";
import { useWorkspace } from "../shell/workspace";

export function ScreenContext() {
  const { fund, asOf } = useWorkspace();
  if (!fund) return null;
  return (
    <p className="muted">
      {fund.name}, {asOf ? dayLabel(asOf) : "no business day loaded yet"}
    </p>
  );
}
