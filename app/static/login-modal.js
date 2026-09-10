// =============================================================
// LOGIN + REGISTER MODAL LOGIC
// =============================================================

// Elements from landing_page.html
const registerButtons = document.querySelectorAll(".register-btn");
const registerModal = document.getElementById("register-modal");
const closeModalBtn = document.getElementById("close-modal-btn");
const submitRegisterBtn = document.getElementById("submit-register-btn");
const emailInput = document.getElementById("email-input");
const emailError = document.getElementById("email-error");
const selectedPlanLabel = document.getElementById("selected-plan-label");

// Debug to confirm JS is loading
console.log("LOGIN JS LOADED");

// =============================================================
// OPEN MODAL
// =============================================================
registerButtons.forEach(btn => {
  btn.addEventListener("click", () => {
    const plan = btn.dataset.plan || "free";
    selectedPlanLabel.textContent = `Register (${plan})`;
    registerModal.classList.remove("hidden");
  });
});

// =============================================================
// CLOSE MODAL
// =============================================================
closeModalBtn.addEventListener("click", () => {
  registerModal.classList.add("hidden");
  emailInput.value = "";
  emailError.textContent = "";
});

// Close modal when clicking outside the content
registerModal.addEventListener("click", (e) => {
  if (e.target === registerModal) {
    registerModal.classList.add("hidden");
    emailInput.value = "";
    emailError.textContent = "";
  }
});

// =============================================================
// EMAIL VALIDATION
// =============================================================
function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// =============================================================
// SUBMIT EMAIL → BACKEND
// =============================================================
submitRegisterBtn.addEventListener("click", async () => {
  const email = emailInput.value.trim();
  emailError.textContent = "";

  if (!isValidEmail(email)) {
    emailError.textContent = "Please enter a valid email address.";
    return;
  }

  try {
    const response = await fetch("/validate_email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email })
    });

    const data = await response.json();

    if (!data.ok) {
      emailError.textContent = data.error || "Corporate email required.";
      return;
    }

    // SUCCESS → redirect to dashboard
    window.location.href = "/dashboard";

  } catch (err) {
    emailError.textContent = "Network error. Please try again.";
  }
});






