/* ---------------------------------------------------------
   THEME SYSTEM — LIGHT / DARK / AUTO
   - Default: auto (light in day, dark at night)
   - User can override: light / dark / auto
   - Uses local time (18:00–06:00 = dark)
--------------------------------------------------------- */

/* Get current theme mode from storage or default to "auto" */
function getStoredThemeMode() {
    const saved = localStorage.getItem("theme-mode");
    if (!saved) return "auto";
    if (saved === "light" || saved === "dark" || saved === "auto") return saved;
    return "auto";
}

/* Decide if it should be dark based on local time */
function isNightTime() {
    const now = new Date();
    const hour = now.getHours();
    // Night = 18:00–23:59 and 00:00–05:59
    return hour >= 18 || hour < 6;
}

/* Apply a specific theme mode to the document */
function applyTheme(mode) {
    const root = document.documentElement;

    if (mode === "light") {
        root.classList.remove("dark-theme");
        root.classList.add("light-theme");
        return;
    }

    if (mode === "dark") {
        root.classList.remove("light-theme");
        root.classList.add("dark-theme");
        return;
    }

    // AUTO MODE
    if (isNightTime()) {
        root.classList.remove("light-theme");
        root.classList.add("dark-theme");
    } else {
        root.classList.remove("dark-theme");
        root.classList.add("light-theme");
    }
}

/* Public: set theme and persist choice */
function setTheme(mode) {
    if (mode !== "light" && mode !== "dark" && mode !== "auto") {
        mode = "auto";
    }
    localStorage.setItem("theme-mode", mode);
    applyTheme(mode);
}

/* Initialize theme on page load */
function initTheme() {
    const mode = getStoredThemeMode();
    applyTheme(mode);
}

/* Optional: wire a <select id="themeSelect"> if it exists */
function initThemeSelector() {
    const select = document.getElementById("themeSelect");
    if (!select) return;

    // Set initial value
    select.value = getStoredThemeMode();

    select.addEventListener("change", (e) => {
        setTheme(e.target.value);
    });
}

/* Run on load */
document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initThemeSelector();
});
