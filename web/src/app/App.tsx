/**
 * The application: providers, then routes. `AppProviders` and `AppRoutes` are separate so
 * tests can mount the same tree inside a memory router.
 */
import * as Tooltip from "@radix-ui/react-tooltip";
import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";

import { makeQueryClient } from "../api/queries";
import { AuthProvider } from "../auth/AuthContext";
import { RequireAuth } from "../auth/RequireAuth";
import { SignInScreen } from "../auth/SignInScreen";
import { KeyboardProvider } from "../keyboard/KeyboardProvider";
import { CasesScreen } from "../screens/cases/CasesScreen";
import { FundsScreen } from "../screens/funds/FundsScreen";
import { NotFoundScreen } from "../screens/NotFoundScreen";
import { OverviewScreen } from "../screens/overview/OverviewScreen";
import { SignOffScreen } from "../screens/signoff/SignOffScreen";
import { UploadScreen } from "../screens/upload/UploadScreen";
import { AppShell } from "../shell/AppShell";
import { ThemeProvider } from "../theme/ThemeProvider";

/** Everything except the router. */
export function AppProviders({ client, children }: { client: QueryClient; children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <AuthProvider>
          <KeyboardProvider>
            <Tooltip.Provider delayDuration={300}>{children}</Tooltip.Provider>
          </KeyboardProvider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

/** "/" opens the overview, keeping any fund and day in the address. */
function Home() {
  const { search } = useLocation();
  return <Navigate to={`/overview${search}`} replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/signin" element={<SignInScreen />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/overview" element={<OverviewScreen />} />
        <Route path="/upload" element={<UploadScreen />} />
        <Route path="/cases" element={<CasesScreen />} />
        <Route path="/signoff" element={<SignOffScreen />} />
        <Route path="/funds" element={<FundsScreen />} />
      </Route>
      <Route path="/" element={<Home />} />
      <Route path="*" element={<NotFoundScreen />} />
    </Routes>
  );
}

export function App() {
  const [client] = useState(makeQueryClient);
  return (
    <BrowserRouter>
      <AppProviders client={client}>
        <AppRoutes />
      </AppProviders>
    </BrowserRouter>
  );
}
