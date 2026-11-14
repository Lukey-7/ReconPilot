/**
 * The frame around every signed-in screen: the top bar, the sticky NAV strip, the screen
 * itself, and the shell's shortcuts (g o, g u, g q, g s, g m, g l, g f, ?).
 */
import { useState } from "react";
import { Outlet, useNavigate } from "react-router";

import { useUser } from "../auth/AuthContext";
import { ErrorLine, Loading } from "../components/QueryState";
import { DemoBanner } from "../demo/DemoBanner";
import { useShortcut } from "../keyboard/KeyboardProvider";
import { HelpDialog } from "./HelpDialog";
import { NavStrip } from "./NavStrip";
import { FUNDS_SCREEN, SCREENS, TopBar } from "./TopBar";
import { WorkspaceProvider, useWorkspace } from "./workspace";

function ScreenShortcuts({ onShowHelp }: { onShowHelp: () => void }) {
  const navigate = useNavigate();
  const { href } = useWorkspace();
  const [overview, upload, cases, signoff, mi, audit] = SCREENS;
  useShortcut(overview.keys, () => navigate(href(overview.path)), { description: "Go to the overview", group: "Go to" });
  useShortcut(upload.keys, () => navigate(href(upload.path)), { description: "Go to upload and run", group: "Go to" });
  useShortcut(cases.keys, () => navigate(href(cases.path)), { description: "Go to the cases", group: "Go to" });
  useShortcut(signoff.keys, () => navigate(href(signoff.path)), { description: "Go to sign-off", group: "Go to" });
  useShortcut(mi.keys, () => navigate(href(mi.path)), { description: "Go to management information", group: "Go to" });
  useShortcut(audit.keys, () => navigate(href(audit.path)), { description: "Go to the audit log", group: "Go to" });
  useShortcut(FUNDS_SCREEN.keys, () => navigate(href(FUNDS_SCREEN.path)), {
    description: "Go to the funds and their settings",
    group: "Go to",
  });
  useShortcut("?", onShowHelp, { description: "Show keyboard shortcuts", group: "General" });
  return null;
}

function Body() {
  const { fundsLoading, fundsError, funds } = useWorkspace();
  if (fundsLoading) return <Loading label="Loading funds" />;
  if (fundsError) return <ErrorLine error={fundsError} />;
  if (!funds.length) {
    return (
      <div className="placeholder">
        <h1>No funds yet</h1>
        <p className="muted">An administrator creates funds with <code>reconpilot-web create-fund</code>.</p>
      </div>
    );
  }
  return <Outlet />;
}

export function AppShell() {
  const [helpOpen, setHelpOpen] = useState(false);
  const user = useUser();
  return (
    <WorkspaceProvider>
      <a className="skip-link" href="#main">
        Skip to the screen
      </a>
      {user.demo && <DemoBanner />}
      <div className="chrome">
        <TopBar onShowHelp={() => setHelpOpen(true)} />
        <NavStrip />
      </div>
      <main id="main" className="main" tabIndex={-1}>
        <Body />
      </main>
      <ScreenShortcuts onShowHelp={() => setHelpOpen(true)} />
      <HelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </WorkspaceProvider>
  );
}
