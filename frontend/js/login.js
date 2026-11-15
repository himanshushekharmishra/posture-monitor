// Login / sign-up page. Talks to /api/auth/* (backend/auth/routes.py).
import { api } from "./api.js";

const $ = (id) => document.getElementById(id);
const USERNAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$/;
const MIN_PASSWORD = 10;

const ICONS = {
  google: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.2-2.1 3.5-5.1 3.5-8.7z"/><path fill="#34A853" d="M12 24c3.2 0 6-1.1 7.9-2.9l-3.9-3c-1 .7-2.4 1.1-4 1.1-3.1 0-5.7-2.1-6.6-4.9h-4v3.1A12 12 0 0 0 12 24z"/><path fill="#FBBC05" d="M5.4 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8l4-3.1z"/><path fill="#EA4335" d="M12 4.8c1.7 0 3.3.6 4.5 1.8l3.4-3.4A12 12 0 0 0 1.4 6.6l4 3.1C6.3 6.9 8.9 4.8 12 4.8z"/></svg>`,
  github: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .5a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2.1c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1.1-.7.1-.7.1-.7 1.2.1 1.9 1.3 1.9 1.3 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17.3 4.6 18.3 5 18.3 5c.7 1.7.3 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .5z"/></svg>`,
  phone: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7 1h10a2 2 0 0 1 2 2v18a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2zm0 3v14h10V4H7zm5 15.5a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4z"/></svg>`,
};

const state = { providers: null, phoneIntent: "login", phone: "", returnView: "login" };

// ---------- messages ----------
// Messages that aren't about a form (an expired sign-up, a Google error) show at the top
// of the card. Anything about a form shows right under the field it's about, or just
// above the form's button, so nobody has to scroll up to see what went wrong.
function showMessage(text, tone = "error") {
  const el = $("message");
  el.textContent = text;
  el.dataset.tone = tone;
  el.hidden = !text;
}

/** A problem with one field; run() shows it under that field. */
class FieldError extends Error {
  constructor(input, message) {
    super(message);
    this.input = input;
  }
}

function describedBy(input, id, add) {
  const ids = new Set((input.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
  if (add) ids.add(id);
  else ids.delete(id);
  if (ids.size) input.setAttribute("aria-describedby", [...ids].join(" "));
  else input.removeAttribute("aria-describedby");
}

function newErrorLine(className) {
  const p = document.createElement("p");
  p.className = className;
  p.setAttribute("role", "alert");
  return p;
}

function showFieldError(input, text) {
  const host = input.closest(".password-field") || input;
  let p = $(`${input.id}-error`);
  if (!p) {
    p = newErrorLine("field-error");
    p.id = `${input.id}-error`;
    host.after(p);
  }
  p.textContent = text;
  input.setAttribute("aria-invalid", "true");
  describedBy(input, p.id, true);
}

function showFormError(form, text) {
  let p = form.querySelector(".form-error");
  if (!p) {
    p = newErrorLine("field-error form-error");
    form.querySelector("[type=submit]").before(p);
  }
  p.textContent = text;
}

function clearFieldError(input) {
  input.removeAttribute("aria-invalid");
  const p = $(`${input.id}-error`);
  if (p) {
    describedBy(input, p.id, false);
    p.remove();
  }
}

function clearErrors(form) {
  form.querySelectorAll("input").forEach(clearFieldError);
  form.querySelector(".form-error")?.remove();
}

const clearAllErrors = () => document.querySelectorAll("form").forEach(clearErrors);

/** Server errors on a sign-up form go under the field they name, else above the button. */
const placeNear = (form) => (err) => {
  const m = err.message;
  const input = /password/i.test(m) ? form.password : /username/i.test(m) ? form.username : null;
  if (input) showFieldError(input, m);
  else showFormError(form, m);
};

// Typing in a field clears its error (and the form's general one, now out of date).
document.addEventListener("input", (e) => {
  const input = e.target;
  if (!(input instanceof HTMLInputElement) || !input.form) return;
  if (input.form.id === "login-form") clearErrors(input.form); // one shared error there
  else clearFieldError(input);
  input.form.querySelector(".form-error")?.remove();
});

/** Run a form action. `place` decides where a server error shows (default: top). */
async function run(button, action, place = null) {
  showMessage("");
  button.disabled = true;
  try {
    await action();
  } catch (err) {
    if (err instanceof FieldError) {
      showFieldError(err.input, err.message);
      err.input.focus();
    } else if (place) {
      place(err);
    } else {
      showMessage(err.message);
    }
  } finally {
    button.disabled = false;
  }
}

// ---------- views ----------
const VIEWS = ["login", "signup", "phone", "complete", "trial"];

function showView(name) {
  for (const v of VIEWS) $(`view-${v}`).hidden = v !== name;
  const onTabs = name === "login" || name === "signup";
  $("tab-login").setAttribute("aria-selected", String(name === "login"));
  $("tab-signup").setAttribute("aria-selected", String(name === "signup"));
  document.querySelector(".auth-switch").hidden = !onTabs;
  const first = $(`view-${name}`).querySelector("input, a.provider, button:not([disabled])");
  if (!onTabs) first?.focus();
}

function switchTo(name) {
  showMessage("");
  clearAllErrors();
  showView(name);
}

$("tab-login").addEventListener("click", () => switchTo("login"));
$("tab-signup").addEventListener("click", () => switchTo("signup"));
document.querySelectorAll("[data-back]").forEach((b) =>
  b.addEventListener("click", () => switchTo(state.returnView)));

// ---------- provider buttons ----------
function providerButton(kind, label, intent, enabled) {
  const content = `${ICONS[kind]}<span>${label}</span>`;
  const name = `Continue with ${label}`;
  if (!enabled) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "provider";
    b.setAttribute("aria-disabled", "true");
    b.setAttribute("aria-label", `${name} (not set up on this server yet)`);
    b.title = "Not set up on this server yet";
    b.innerHTML = `${content}<small>(not set up)</small>`;
    return b;
  }
  if (kind === "phone") {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "provider";
    b.setAttribute("aria-label", name);
    b.innerHTML = content;
    b.addEventListener("click", () => openPhone(intent));
    return b;
  }
  const a = document.createElement("a");
  a.className = "provider";
  a.href = `/auth/${kind}/start?intent=${intent}`;
  a.setAttribute("aria-label", name);
  a.innerHTML = content;
  return a;
}

function renderProviders() {
  const p = state.providers;
  document.querySelectorAll(".providers").forEach((box) => {
    const intent = box.dataset.intent;
    box.replaceChildren(
      providerButton("google", "Google", intent, p.google),
      providerButton("github", "GitHub", intent, p.github),
      providerButton("phone", "Phone number", intent, p.phone),
    );
  });
  $("guest-note").textContent =
    `Free ${p.guest_trial_days}-day trial with just a username and password. ` +
    "Connect Google, GitHub or a phone later to keep your account.";
}

// ---------- form helpers ----------
function invalid(input, message) {
  throw new FieldError(input, message);
}

function checkNewAccount(form) {
  clearErrors(form);
  const username = form.username.value.trim();
  if (!USERNAME_RE.test(username)) {
    invalid(form.username, "Username must be 3-32 letters, numbers, dots, dashes or underscores.");
  }
  if (form.password.value.length < MIN_PASSWORD) {
    invalid(form.password, `Password must be at least ${MIN_PASSWORD} characters.`);
  }
  if (form.password.value !== form.confirm.value) {
    invalid(form.confirm, "The passwords don't match.");
  }
  return { username, password: form.password.value };
}

document.querySelectorAll(".show-password").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = btn.previousElementSibling;
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.textContent = show ? "Hide" : "Show";
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
});

const goToApp = () => location.assign("/");

// ---------- log in ----------
$("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  run(form.querySelector("[type=submit]"), async () => {
    clearErrors(form);
    if (!form.username.value.trim()) invalid(form.username, "Enter your username.");
    if (!form.password.value) invalid(form.password, "Enter your password.");
    await api("/api/auth/login", {
      username: form.username.value.trim(), password: form.password.value,
    });
    goToApp();
  }, (err) => {
    // "Wrong username or password": either could be at fault, so mark both and say it
    // under the password, right above the button.
    if (err.status === 401) form.username.setAttribute("aria-invalid", "true");
    showFieldError(form.password, err.message);
  });
});

// ---------- guest trial ----------
$("guest-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  run(form.querySelector("[type=submit]"), async () => {
    const { username, password } = checkNewAccount(form);
    await api("/api/auth/signup", { username, password, guest: true });
    goToApp();
  }, placeNear(form));
});

// ---------- phone ----------
function openPhone(intent) {
  state.phoneIntent = intent;
  state.returnView = intent === "link" ? "trial" : $("view-signup").hidden ? "login" : "signup";
  $("phone-form").hidden = false;
  $("code-form").hidden = true;
  showMessage("");
  clearAllErrors();
  showView("phone");
}

async function sendCode(button) {
  const resending = $("phone-form").hidden;
  clearErrors(resending ? $("code-form") : $("phone-form"));
  await run(button, async () => {
    const res = await api("/api/auth/phone/send", { phone: state.phone });
    $("sent-to").textContent = res.sent_to;
    $("dev-sms").hidden = !res.dev_mode;
    $("phone-form").hidden = true;
    $("code-form").hidden = false;
    $("code").value = "";
    $("code").focus();
  }, (err) => {
    if (resending) showFormError($("code-form"), err.message);
    else showFieldError($("phone"), err.message);
  });
}

$("phone-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  clearErrors(form);
  state.phone = form.phone.value.trim();
  if (!/^\+\d[\d\s().-]{6,}$/.test(state.phone)) {
    showFieldError(form.phone, "Enter the number with its country code, like +91 98765 43210.");
    form.phone.focus();
    return;
  }
  sendCode(form.querySelector("[type=submit]"));
});

$("resend").addEventListener("click", (e) => sendCode(e.currentTarget));

$("code-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  run(form.querySelector("[type=submit]"), async () => {
    clearErrors(form);
    if (!/^\d{6}$/.test(form.code.value)) invalid(form.code, "Enter the 6-digit code.");
    const res = await api("/api/auth/phone/verify", {
      phone: state.phone, code: form.code.value, intent: state.phoneIntent,
    });
    if (res.status === "needs_account") await openComplete();
    else goToApp();
  }, (err) => showFieldError(form.code, err.message));
});

// ---------- finish sign-up after verifying ----------
const PROVIDER_NAMES = { google: "Google", github: "GitHub", phone: "your phone" };

async function openComplete() {
  let pending;
  try {
    pending = await api("/api/auth/pending");
  } catch {
    showView("signup");
    showMessage("That sign-up took too long and expired. Verify again to continue.");
    return;
  }
  $("verified-as").textContent =
    `Verified with ${PROVIDER_NAMES[pending.provider]}` +
    (pending.verified_as ? ` as ${pending.verified_as}.` : ".");
  if (pending.suggested_name) $("complete-name").value = pending.suggested_name;
  showView("complete");
}

$("complete-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  run(form.querySelector("[type=submit]"), async () => {
    const { username, password } = checkNewAccount(form);
    await api("/api/auth/signup", {
      username, password, display_name: form.display_name.value.trim() || null,
    });
    goToApp();
  }, placeNear(form));
});

// ---------- trial over ----------
$("logout").addEventListener("click", (e) =>
  run(e.currentTarget, async () => {
    await api("/api/auth/logout", {});
    location.replace("/login.html");
  }));

// ---------- start ----------
async function init() {
  const params = new URLSearchParams(location.search);
  const error = params.get("error");
  if (params.has("error")) history.replaceState(null, "", location.pathname + location.hash);

  try {
    state.providers = await api("/api/auth/providers");
  } catch (err) {
    showMessage(err.message);
    return;
  }
  renderProviders();

  if (location.hash === "#complete") {
    history.replaceState(null, "", location.pathname);
    await openComplete();
  } else if (location.hash === "#trial-ended") {
    showView("trial");
  } else {
    showView("login");
  }
  if (error) showMessage(error);
}

init();
