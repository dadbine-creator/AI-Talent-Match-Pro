// Apply theme on page load
document.addEventListener("DOMContentLoaded", () => {
    const savedTheme = localStorage.getItem("theme-preference") || "auto";
    applyTheme(savedTheme);
});

// Dropdown toggle
const themeBtn = document.getElementById("themeToggleBtn");
const themeMenu = document.getElementById("themeMenu");

themeBtn.addEventListener("click", () => {
    themeMenu.style.display =
        themeMenu.style.display === "flex" ? "none" : "flex";
});

// Handle theme selection
document.querySelectorAll(".theme-option").forEach(option => {
    option.addEventListener("click", () => {
        const theme = option.dataset.theme;
        localStorage.setItem("theme-preference", theme);
        applyTheme(theme);
        themeMenu.style.display = "none";
    });
});

// Apply theme logic
function applyTheme(mode) {

    // ⭐ Add cinematic fade transition
    document.documentElement.classList.add("theme-transition");
    setTimeout(() => {
        document.documentElement.classList.remove("theme-transition");
    }, 450);

    if (mode === "light") {
        document.documentElement.className = "light-theme";
        themeBtn.textContent = "☀️";
        return;
    }

    if (mode === "dark") {
        document.documentElement.className = "dark-theme";
        themeBtn.textContent = "🌙";
        return;
    }

    // AUTO MODE (sunset logic)
    const now = new Date();
    const hours = now.getHours();

    // Simple sunset logic: dark after 18:00, light before
    if (hours >= 18 || hours < 6) {
        document.documentElement.className = "dark-theme";
        themeBtn.textContent = "🌙";
    } else {
        document.documentElement.className = "light-theme";
        themeBtn.textContent = "☀️";
    }
}

