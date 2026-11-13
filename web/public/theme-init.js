// Applies the theme the user chose (light or dark) before React starts, so the page
// never flashes the other theme. With no saved choice the page follows the system.
// Keep the storage key in step with src/theme/ThemeProvider.tsx.
(function () {
  try {
    const saved = window.localStorage.getItem("rp-theme");
    if (saved === "light" || saved === "dark") document.documentElement.setAttribute("data-theme", saved);
  } catch {
    /* storage blocked: follow the system */
  }
})();
