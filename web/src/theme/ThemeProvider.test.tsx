import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mediaMatches } from "../test/setup";
import { THEME_STORAGE_KEY, ThemeProvider, ThemeToggle, useTheme } from "./ThemeProvider";

function Show() {
  const { theme, preference } = useTheme();
  return (
    <p>
      {theme} / {preference}
    </p>
  );
}

function renderTheme() {
  return render(
    <ThemeProvider>
      <Show />
      <ThemeToggle />
    </ThemeProvider>,
  );
}

describe("theme", () => {
  it("is dark by default", () => {
    renderTheme();
    expect(screen.getByText("dark / dark")).toBeInTheDocument();
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("stays dark when the system prefers light", () => {
    mediaMatches.add("(prefers-color-scheme: light)");
    renderTheme();
    expect(screen.getByText("dark / dark")).toBeInTheDocument();
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("toggles to light, remembers it, and back to dark", async () => {
    renderTheme();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Switch to the light theme" }));
    expect(screen.getByText("light / light")).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    await user.click(screen.getByRole("button", { name: "Switch to the dark theme" }));
    expect(screen.getByText("dark / dark")).toBeInTheDocument();
    expect(document.documentElement).not.toHaveAttribute("data-theme");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it("restores a saved choice", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    renderTheme();
    expect(screen.getByText("light / light")).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });
});
