/**
 * Theme: Night desk dark by default, a light theme for accessibility.
 *
 * With no choice saved the page follows the system (`prefers-color-scheme`), as the
 * tokens in styles/tokens.css do on their own. The toggle switches to the other theme;
 * choosing the theme the system already prefers clears the choice, so the page goes back
 * to following the system. The choice is kept in localStorage under `rp-theme` and
 * applied before first paint by public/theme-init.js.
 */
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { Icon } from "../components/Icon";

export const THEME_STORAGE_KEY = "rp-theme";
export type Theme = "light" | "dark";
export type ThemePreference = Theme | "system";

function readPreference(): ThemePreference {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

function writePreference(pref: ThemePreference): void {
  try {
    if (pref === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, pref);
  } catch {
    /* storage blocked: the choice lasts for this page only */
  }
}

const LIGHT_QUERY = "(prefers-color-scheme: light)";

function systemTheme(): Theme {
  return typeof window.matchMedia === "function" && window.matchMedia(LIGHT_QUERY).matches ? "light" : "dark";
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
  const [system, setSystem] = useState<Theme>(systemTheme);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(LIGHT_QUERY);
    const onChange = () => setSystem(query.matches ? "light" : "dark");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (preference === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", preference);
  }, [preference]);

  const setPreference = useCallback((pref: ThemePreference) => {
    writePreference(pref);
    setPreferenceState(pref);
  }, []);

  const theme: Theme = preference === "system" ? system : preference;

  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setPreference(next === system ? "system" : next);
  }, [theme, system, setPreference]);

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
    <button type="button" className="btn ghost icon-btn" onClick={toggle} aria-label={`Switch to the ${next} theme`}>
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}
