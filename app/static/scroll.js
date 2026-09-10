// OPEN MODAL
document.querySelectorAll(".register-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const plan = btn.getAttribute("data-plan");
    document.getElementById("selected-plan-label").textContent =
      plan.charAt(0).toUpperCase() + plan.slice(1) + " Plan";

    document.getElementById("register-modal").classList.remove("hidden");
  });
});

// CLOSE MODAL
document.getElementById("close-modal-btn").addEventListener("click", () => {
  document.getElementById("register-modal").classList.add("hidden");
});

// VALIDATE EMAIL
document.getElementById("submit-register-btn").addEventListener("click", () => {
  const emailInput = document.getElementById("email-input");
  const error = document.getElementById("email-error");

  if (!emailInput.value.includes("@") || !emailInput.value.includes(".")) {
    error.textContent = "Please enter a valid corporate email.";
    return;
  }

  error.textContent = "";
  window.location.href = "/register?email=" + encodeURIComponent(emailInput.value);
});
































