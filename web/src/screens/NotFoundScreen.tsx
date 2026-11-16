import { useEffect } from "react";
import { Link } from "react-router";

export function NotFoundScreen() {
  useEffect(() => {
    document.title = "Page not found · ReconPilot";
  }, []);
  return (
    <main className="placeholder not-found">
      <h1>Page not found</h1>
      <p className="muted">
        There is no page here. <Link to="/overview">Go to the overview</Link>.
      </p>
    </main>
  );
}
