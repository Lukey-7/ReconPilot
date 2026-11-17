// Applies the light theme before React starts when the user chose it, so the page never
// flashes dark first. With no saved choice the page is dark (Night desk), whatever the
// system prefers. Keep the storage key in step with src/theme/ThemeProvider.tsx.
(function () {
  try {
    if (window.localStorage.getItem("rp-theme") === "light") document.documentElement.setAttribute("data-theme", "light");
  } catch {
    /* storage blocked: stay dark */
  }
})();
