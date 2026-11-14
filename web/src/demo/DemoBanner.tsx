/**
 * The permanent notice on every page of the public demo: the data is synthetic. Shown on
 * sign-in and above every signed-in screen; it cannot be closed.
 */
import "./demo.css";

import { Icon } from "../components/Icon";

export function DemoBanner({ hours = 24 }: { hours?: number }) {
  return (
    <div className="demo-banner" role="note" aria-label="Demo notice">
      <Icon name="warn" />
      <p>
        <strong>Demo.</strong> Every figure here is synthetic, generated from a fixed seed; no real fund, trade or
        person is shown. Your fund is yours alone and is deleted {hours} hours after you last use it.
      </p>
    </div>
  );
}
