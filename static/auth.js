
async function submitAuthForm(form, endpoint) {
  const status = document.getElementById("auth-status");
  const button = form.querySelector('button[type="submit"]');
  const email = form.elements.email.value.trim();
  const password = form.elements.password.value;

  status.textContent = "";
  status.className = "auth-status";

  if (endpoint === "/auth/register") {
    const confirmation = form.elements["confirm-password"].value;

    if (password !== confirmation) {
      status.textContent = "Passwords do not match.";
      status.classList.add("error");
      return;
    }
  }

  button.disabled = true;
  button.textContent = "Please wait…";

  try {
    const payload = { email, password };
    if (endpoint === "/auth/register") {
      payload.first_name = form.elements.first_name.value.trim();
      payload.last_name = form.elements.last_name.value.trim();
    }

    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload)
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Something went wrong. Please try again.");
    }

    status.textContent = data.message || "Request completed.";
    status.classList.add("success");

    
if (endpoint === "/auth/login") {
  sessionStorage.setItem("getoffdeals_show_welcome", "1");
  window.location.assign("/");
} else {
  form.reset();

  // Allow the user to read the email verification message.
  button.disabled = true;
  button.textContent = "Registration successful";

  setTimeout(() => {
    window.location.assign("/login");
  }, 2500);

  return;
}

  } catch (error) {
    status.textContent = error.message || "Unable to connect. Please try again.";
    status.classList.add("error");
  } finally {
    button.disabled = false;
    button.textContent =
      endpoint === "/auth/login" ? "Sign in ↗" : "Create account ↗";
  }
}

document.getElementById("login-form")?.addEventListener("submit", event => {
  event.preventDefault();
  submitAuthForm(event.currentTarget, "/auth/login");
});

document.getElementById("register-form")?.addEventListener("submit", event => {
  event.preventDefault();
  submitAuthForm(event.currentTarget, "/auth/register");
});
