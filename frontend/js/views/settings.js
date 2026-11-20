// Settings: personal info, connected accounts, password, and deleting the account.
import { api } from "../api.js";
import { el, setStatus, toast } from "../dom.js";

const $ = (id) => document.getElementById(id);
const PROVIDERS = [
  ["google", "Google"],
  ["github", "GitHub"],
  ["phone", "Phone number"],
];
const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$/;
let me = null;

function mark(input, bad) {
  if (bad) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

function renderConnections(providers) {
  const list = $("connections");
  list.replaceChildren(...PROVIDERS.map(([key, name]) => {
    let action;
    if (me.linked.includes(key)) {
      action = el("span", { class: "linked" }, "Connected");
    } else if (!providers[key]) {
      action = el("span", { class: "state" }, "Not set up on this server");
    } else if (key === "phone") {
      action = el("button", { type: "button", class: "quiet", onclick: () => {
        $("link-phone-form").hidden = false;
        $("link-phone").focus();
      } }, "Connect");
    } else {
      action = el("a", { class: "connect", href: `/auth/${key}/start?intent=link` }, "Connect");
    }
    return el("li", {}, el("span", { class: "name" }, name), action);
  }));
}

async function load() {
  let providers;
  try {
    [me, providers] = await Promise.all([api("/api/auth/me"), api("/api/auth/providers")]);
  } catch (err) {
    toast(err.message);
    return;
  }
  $("set-name").value = me.display_name || "";
  $("set-email").value = me.email || "";
  renderConnections(providers);
}

// ---------- personal info ----------
$("profile-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const email = form.email.value.trim();
  mark(form.email, email && !EMAIL_RE.test(email));
  if (email && !EMAIL_RE.test(email)) {
    setStatus(form, "That email address doesn't look right.", "error");
    return;
  }
  try {
    me = await api("/api/account/profile", { display_name: form.display_name.value, email });
    document.getElementById("account-name").textContent = me.display_name || me.username;
    setStatus(form, "Saved.", "ok");
  } catch (err) {
    setStatus(form, err.message, "error");
  }
});

// ---------- connect a phone ----------
let linkPhone = "";
$("link-phone-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  linkPhone = form.phone.value.trim();
  try {
    const res = await api("/api/auth/phone/send", { phone: linkPhone });
    for (const id of ["link-code", "link-verify"]) $(id).hidden = false;
    form.querySelector("label[for=link-code]").hidden = false;
    setStatus(form, res.dev_mode
      ? `Code sent to ${res.sent_to}. SMS isn't set up, so it's in the server's console window.`
      : `Code sent to ${res.sent_to}.`, "ok");
    $("link-code").focus();
  } catch (err) {
    setStatus(form, err.message, "error");
  }
});

$("link-verify").addEventListener("click", async () => {
  const form = $("link-phone-form");
  const code = $("link-code").value.trim();
  if (!/^\d{6}$/.test(code)) {
    setStatus(form, "Enter the 6-digit code.", "error");
    return;
  }
  try {
    await api("/api/auth/phone/verify", { phone: linkPhone, code, intent: "link" });
    form.hidden = true;
    form.reset();
    setStatus(form, "");
    document.getElementById("trial-banner").hidden = true;
    toast("Phone connected.");
    await load();
  } catch (err) {
    setStatus(form, err.message, "error");
  }
});

// ---------- password ----------
$("password-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  for (const i of form.querySelectorAll("input")) mark(i, false);
  if (form.new.value.length < 10) {
    mark(form.new, true);
    setStatus(form, "The new password needs at least 10 characters.", "error");
    return;
  }
  if (form.new.value !== form.confirm.value) {
    mark(form.confirm, true);
    setStatus(form, "The new passwords don't match.", "error");
    return;
  }
  try {
    await api("/api/account/password", {
      current_password: form.current.value, new_password: form.new.value,
    });
    form.reset();
    setStatus(form, "Password changed. Other devices have been logged out.", "ok");
  } catch (err) {
    if (err.status === 403) mark(form.current, true);
    setStatus(form, err.message, "error");
  }
});

// ---------- delete: one button, then "Are you sure?" ----------
const deleteDialog = $("delete-dialog");

$("delete-btn").addEventListener("click", () => {
  setStatus($("delete-block"), "");
  deleteDialog.showModal(); // "No" has focus; Escape also closes it
});

$("delete-no").addEventListener("click", () => deleteDialog.close());

// A click on the dimmed backdrop (outside the box) counts as "No".
deleteDialog.addEventListener("click", (e) => {
  if (e.target === deleteDialog) deleteDialog.close();
});

$("delete-yes").addEventListener("click", async () => {
  const yes = $("delete-yes");
  yes.disabled = true;
  try {
    await api("/api/account/delete", {});
    location.replace("/login.html");
  } catch (err) {
    deleteDialog.close();
    setStatus($("delete-block"), err.message, "error");
  } finally {
    yes.disabled = false;
  }
});

export const settingsView = { show: load };
