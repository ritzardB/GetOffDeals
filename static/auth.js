function setAuthStatus(status, message, type = "") {
  if (!status) return;

  status.textContent = message;
  status.className = "auth-status";

  if (type) status.classList.add(type);
}

async function submitAuthForm(form, endpoint) {
  const status = document.getElementById("auth-status");
  const button = form.querySelector('button[type="submit"]');
  const originalText =
    endpoint === "/auth/login" ? "Sign in ↗" : "Create account ↗";

  const email = form.elements.email.value.trim();
  const password = form.elements.password.value;

  setAuthStatus(status, "");

  if (endpoint === "/auth/register") {
    const confirmation = form.elements["confirm-password"].value;

    if (password !== confirmation) {
      setAuthStatus(status, "Passwords do not match.", "error");
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
      throw new Error(
        data.error || "Something went wrong. Please try again."
      );
    }

    setAuthStatus(
      status,
      data.message || "Request completed.",
      "success"
    );

    if (endpoint === "/auth/login") {
      sessionStorage.setItem("getoffdeals_show_welcome", "1");
      window.location.assign("/");
      return;
    }

    form.reset();
    button.textContent = "Registration successful";

    setTimeout(() => {
      window.location.assign("/login");
    }, 2500);
  } catch (error) {
    setAuthStatus(
      status,
      error.message || "Unable to connect. Please try again.",
      "error"
    );
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function submitForgotPassword(form) {
  const status = document.getElementById("auth-status");
  const button = form.querySelector('button[type="submit"]');
  const email = form.elements.email.value.trim();

  setAuthStatus(status, "");
  button.disabled = true;
  button.textContent = "Sending…";

  try {
    const response = await fetch("/auth/forgot-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ email })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.error || "Unable to send the recovery request."
      );
    }

    form.reset();

    setAuthStatus(
      status,
      data.message ||
        "If an account exists for that email, a recovery link will be sent.",
      "success"
    );
  } catch (error) {
    setAuthStatus(
      status,
      error.message || "Unable to connect. Please try again.",
      "error"
    );
  } finally {
    button.disabled = false;
    button.textContent = "Send recovery link";
  }
}

function getRecoveryToken() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get("access_token");
  const type = params.get("type");

  // Only accept tokens from a Supabase recovery link.
  if (type !== "recovery" || !token) {
    return null;
  }

  // Remove the token from the visible URL after reading it.
  // Keep the current page and path unchanged.
  window.history.replaceState(
    null,
    document.title,
    window.location.pathname + window.location.search
  );

  return token;
}

async function submitResetPassword(form, recoveryToken) {
  const status = document.getElementById("auth-status");
  const button = form.querySelector('button[type="submit"]');
  const password = form.elements.password.value;
  const confirmation = form.elements["confirm-password"].value;

  setAuthStatus(status, "");

  if (!recoveryToken) {
    setAuthStatus(
      status,
      "Your recovery link is invalid or expired. Request a new one.",
      "error"
    );
    return;
  }

  if (password.length < 8 || password.length > 128) {
    setAuthStatus(
      status,
      "Password must be between 8 and 128 characters.",
      "error"
    );
    return;
  }

  if (password !== confirmation) {
    setAuthStatus(status, "Passwords do not match.", "error");
    return;
  }

  button.disabled = true;
  button.textContent = "Updating…";

  try {
    const response = await fetch("/auth/reset-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        access_token: recoveryToken,
        password
      })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.error || "Unable to update your password."
      );
    }

    form.reset();
    setAuthStatus(
      status,
      data.message || "Password updated. You can now sign in.",
      "success"
    );

    // Prevent accidental reuse of this token in the current page.
    recoveryToken = null;
    button.textContent = "Password updated";

    setTimeout(() => {
      window.location.assign("/login");
    }, 2000);
  } catch (error) {
    setAuthStatus(
      status,
      error.message || "Unable to connect. Please try again.",
      "error"
    );
  } finally {
    if (button.isConnected && recoveryToken !== null) {
      button.disabled = false;
      button.textContent = "Update password";
    }
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

document
  .getElementById("forgot-password-form")
  ?.addEventListener("submit", event => {
    event.preventDefault();
    submitForgotPassword(event.currentTarget);
  });

const resetPasswordForm =
  document.getElementById("reset-password-form");

if (resetPasswordForm) {
  const recoveryToken = getRecoveryToken();

  if (!recoveryToken) {
    setAuthStatus(
      document.getElementById("auth-status"),
      "Open the recovery link from your email. If it has expired, request a new one.",
      "error"
    );
  }

  resetPasswordForm.addEventListener("submit", event => {
    event.preventDefault();
    submitResetPassword(event.currentTarget, recoveryToken);
  });
}
