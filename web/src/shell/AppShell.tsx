/**
 * The frame around every signed-in screen: the top bar, the sticky NAV strip, the screen
 * itself, the shell's shortcuts (g o, g u, g q, g s, g m, g l, g f, ?, Ctrl+K) and the
 * actions any screen offers in the command palette (theme, shortcuts, sign out, and the
 * demo's "Work as").
 */
import { useState } from "react";
import { Outlet, useNavigate } from "react-router";

import type { DemoMember } from "../api/types";
import { useAuth, useUser } from "../auth/AuthContext";
import { ErrorLine, Loading } from "../components/QueryState";
import { DemoBanner } from "../demo/DemoBanner";
import { useCommand, useShortcut } from "../keyboard/KeyboardProvider";
import { useTheme } from "../theme/ThemeProvider";
import { roleLabel } from "../vocabulary";
import { CommandPalette } from "./CommandPalette";
import { HelpDialog } from "./HelpDialog";
import { NavStrip } from "./NavStrip";
import { FUNDS_SCREEN, SCREENS, TopBar } from "./TopBar";
import { WorkspaceProvider, useWorkspace } from "./workspace";

function ScreenShortcuts({ onShowHelp, onOpenPalette }: { onShowHelp: () => void; onOpenPalette: () => void }) {
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
  useShortcut("?", onShowHelp, { description: "Show keyboard shortcuts", group: "General", palette: true });
  useShortcut("mod+k", onOpenPalette, {
    description: "Jump to a case, screen, fund or day, or run an action",
    group: "General",
    whileTyping: true,
  });
  return null;
}

/** The demo's "Work as": one action for each of the fund's other users. */
function WorkAs({ member }: { member: DemoMember }) {
  const { switchUser } = useAuth();
  useCommand(`Work as ${member.display_name} (${roleLabel(member.role).toLowerCase()})`, () => void switchUser(member.username).catch(() => {}), {
    group: "General",
    keywords: `switch user role demo ${member.role}`,
  });
  return null;
}

function ShellCommands() {
  const user = useUser();
  const { signOut } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  useCommand(`Switch to the ${theme === "dark" ? "light" : "dark"} theme`, toggle, { group: "General", keywords: "theme colour dark light" });
  useCommand(
    "Sign out",
    () => {
      void signOut().then(() => navigate("/signin", { replace: true }));
    },
    { group: "General", keywords: "log out leave" },
  );
  const others = (user.demo?.users ?? []).filter((m) => m.username !== user.username);
  return (
    <>
      {others.map((m) => (
        <WorkAs key={m.username} member={m} />
      ))}
    </>
  );
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
  const [paletteOpen, setPaletteOpen] = useState(false);
  const user = useUser();
  return (
    <WorkspaceProvider>
      <a className="skip-link" href="#main">
        Skip to the screen
      </a>
      {user.demo && <DemoBanner />}
      <div className="chrome">
        <TopBar onShowHelp={() => setHelpOpen(true)} onOpenPalette={() => setPaletteOpen(true)} />
        <NavStrip />
      </div>
      <main id="main" className="main" tabIndex={-1}>
        <Body />
      </main>
      <ScreenShortcuts onShowHelp={() => setHelpOpen(true)} onOpenPalette={() => setPaletteOpen((open) => !open)} />
      <ShellCommands />
      <HelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </WorkspaceProvider>
  );
}
