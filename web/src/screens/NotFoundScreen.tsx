import { useEffect } from "react";
import { Link } from "react-router";

import { Icon } from "../components/Icon";

/** A calm, centred empty state with its one way back. */
export function NotFoundScreen() {
  useEffect(() => {
    document.title = "Page not found · ReconPilot";
  }, []);
  return (
    <main className="not-found">
      <section className="card empty-state not-found-card" aria-labelledby="nf-h">
        <span className="tile-box" aria-hidden="true">
          <Icon name="search" />
        </span>
        <h1 id="nf-h">Page not found</h1>
        <p>There is no page here.</p>
        <Link className="btn primary" to="/overview">
          Go to the overview
        </Link>
      </section>
    </main>
  );
}
