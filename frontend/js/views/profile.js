// Profile: who you are, how you sign in, and your lifetime numbers.
import { api } from "../api.js";
import { el, minutesText, perHourText } from "../dom.js";

const PROVIDERS = { google: "Google", github: "GitHub", phone: "Phone" };

function initials(name) {
  const parts = name.trim().split(/[\s_.-]+/).filter(Boolean);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
}

function accountType(me) {
  if (!me.is_guest) return "Verified account";
  if (me.trial_expired) return "Guest trial (ended)";
  const d = me.trial_days_left;
  return `Guest trial, ${d} day${d === 1 ? "" : "s"} left`;
}

function figure(value, label) {
  return el("div", {}, el("span", { class: "value" }, value), el("span", { class: "label" }, label));
}

async function load() {
  const body = document.getElementById("profile-body");
  let me;
  let insights;
  try {
    [me, insights] = await Promise.all([api("/api/auth/me"), api("/api/insights?days=7")]);
  } catch (err) {
    body.replaceChildren(el("p", { class: "chart-empty" }, err.message));
    return;
  }
  const name = me.display_name || me.username;
  const t = insights.totals;
  const signIn = ["Username and password", ...me.linked.map((p) => PROVIDERS[p] || p)];
  const since = me.created_at
    ? new Date(me.created_at).toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" })
    : "–";
  const slouchShare = t.hours > 0 ? `${Math.round((t.slouch_minutes / 60 / t.hours) * 100)}%` : "–";

  body.replaceChildren(
    el("div", { class: "profile-card" },
      el("div", { class: "avatar", "aria-hidden": "true" }, initials(name)),
      el("div", {},
        el("p", { class: "profile-name" }, name),
        el("p", { class: "profile-sub" }, `@${me.username}`))),
    el("dl", { class: "detail-list" },
      el("dt", {}, "Account"), el("dd", {}, accountType(me)),
      el("dt", {}, "Member since"), el("dd", {}, since),
      el("dt", {}, "Signs in with"), el("dd", {}, signIn.join(", ")),
      el("dt", {}, "Contact email"), el("dd", {}, me.email || "Not added"),
      el("dt", {}, "Phone"), el("dd", {}, me.phone || "Not connected")),
    el("h3", {}, "All time"),
    el("div", { class: "figures" },
      figure(minutesText(t.hours * 60), "monitored"),
      figure(String(t.sessions), "sessions"),
      figure(String(t.slouches), "slouches"),
      figure(perHourText(t.per_hour), "slouches per hour"),
      figure(slouchShare, "of the time slouching")),
    el("p", {}, el("a", { href: "#settings" }, "Edit personal info")),
  );
}

export const profileView = { show: load };
