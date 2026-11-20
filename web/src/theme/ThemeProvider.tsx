/**
 * Theme: Midnight (dark) by default, Paper (light) by choice.
 *
 * Dark whatever the system prefers (the owner's decision: dark is the default); light only
 * when the user chooses it with the theme button. The choice of light is kept in
 * localStorage under `rp-theme` and applied before first paint by public/theme-init.js;
 * switching back to dark clears it.
 */
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { Icon } from "../components/Icon";

export const THEME_STORAGE_KEY = "rp-theme";
export type Theme = "light" | "dark";
/** What the user chose; with nothing saved, dark. */
export type ThemePreference = Theme;

function readPreference(): ThemePreference {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function writePreference(pref: ThemePreference): void {
  try {
    if (pref === "dark") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, pref);
  } catch {
    /* storage blocked: the choice lasts for this page only */
  }
}

interface ThemeValue {
  /** The theme on screen. */
  theme: Theme;
  preference: ThemePreference;
  setPreference: (pref: ThemePreference) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);

  useEffect(() => {
    const root = document.documentElement;
    if (preference === "light") root.setAttribute("data-theme", "light");
    else root.removeAttribute("data-theme");
  }, [preference]);

  const setPreference = useCallback((pref: ThemePreference) => {
    writePreference(pref);
    setPreferenceState(pref);
  }, []);

  const theme: Theme = preference;

  const toggle = useCallback(() => {
    setPreference(theme === "dark" ? "light" : "dark");
  }, [theme, setPreference]);

  const value = useMemo(() => ({ theme, preference, setPreference, toggle }), [theme, preference, setPreference, toggle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme needs a ThemeProvider");
  return value;
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" className="glass-btn" onClick={toggle} aria-label={`Switch to the ${next} theme`}>
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}
