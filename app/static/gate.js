// GATE LOGIC — Corporate Email Validation + Fade Transition

const gateSubmit = document.getElementById("gate-submit");
const gateEmail = document.getElementById("gate-email");
const gateError = document.getElementById("gate-error");

if (gateSubmit) {
  gateSubmit.addEventListener("click", async () => {
    const email = gateEmail.value.trim();

    // Clear previous error
    gateEmail.classList.remove("error");
    gateError.style.display = "none";

    if (!email) {
      gateEmail.classList.add("error");
      gateError.textContent = "Corporate email required.";
      gateError.style.display = "block";
      return;
    }

    try {
      const res = await fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email })
      });

      const data = await res.json();

      if (!data.ok) {
        gateEmail.classList.add("error");
        gateError.textContent = "Please use a verified corporate email.";
        gateError.style.display = "block";
        return;
      }

      // VALID → fade out and redirect
      document.body.classList.add("fade-out");
      setTimeout(() => {
        window.location.href = "/dashboard";
      }, 600);

    } catch (err) {
      gateEmail.classList.add("error");
      gateError.textContent = "Something went wrong. Please try again.";
      gateError.style.display = "block";
    }
  });
}

