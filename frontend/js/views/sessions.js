// Previous sessions: newest first, expandable to a timeline of what happened.
import { api } from "../api.js";
import { dateTimeLabel, el, minutesText, percentText, timeLabel } from "../dom.js";

const $ = (id) => document.getElementById(id);
const STATUS = { live: "Running now", interrupted: "Ended unexpectedly" };
const EVENT_TEXT = {
  slouch_start: "Started slouching",
  alert: "Alert sent",
  recovered: "Sat up again",
  away: "Left the camera",
};
let nextBefore = null;

function header() {
  return el("div", { class: "session-head", "aria-hidden": "true" },
    el("span", {}, "Started"), el("span", {}, "Length"), el("span", {}, "Slouches"),
    el("span", { class: "hide-narrow" }, "Time slouching"),
    el("span", { class: "hide-narrow" }, "Alerts"), el("span", {}));
}

async function toggle(row, s) {
  const open = row.dataset.open === "true";
  row.dataset.open = String(!open);
  row.querySelector("button").setAttribute("aria-expanded", String(!open));
  const existing = row.querySelector(".timeline, .chart-empty");
  if (open) {
    existing?.remove();
    return;
  }
  let detail;
  try {
    detail = await api(`/api/sessions/${s.id}`);
  } catch (err) {
    row.append(el("p", { class: "chart-empty" }, err.message));
    return;
  }
  if (!detail.events.length) {
    row.append(el("p", { class: "chart-empty" }, "No slouches in this session."));
    return;
  }
  row.append(el("ol", { class: "timeline" }, detail.events.map((e) =>
    el("li", {}, el("time", { datetime: e.ts }, timeLabel(e.ts)),
      el("span", { class: `ev-${e.type}` }, EVENT_TEXT[e.type] || e.type)))));
}

function sessionRow(s) {
  const row = el("div", { class: "session-row", dataset: { open: "false" } });
  const label = `${dateTimeLabel(s.started_at)}, ${minutesText(s.minutes)}, ` +
    `${s.slouches} slouches, ${s.alerts} alerts`;
  row.append(el("button", {
    type: "button", "aria-expanded": "false", "aria-label": label,
    onclick: () => toggle(row, s),
  },
  el("span", { class: "when" }, dateTimeLabel(s.started_at),
    s.status !== "ended"
      ? el("span", { class: "muted status-tag", dataset: { status: s.status } }, STATUS[s.status])
      : null),
  el("span", {}, minutesText(s.minutes)),
  el("span", {}, s.slouches),
  el("span", { class: "hide-narrow" }, `${minutesText(s.slouch_minutes)} (${percentText(s.slouch_share)})`),
  el("span", { class: "hide-narrow" }, s.alerts),
  el("span", { class: "chev", "aria-hidden": "true" }, "›")));
  return row;
}

async function load(append = false) {
  const list = $("session-list");
  const url = append && nextBefore ? `/api/sessions?limit=20&before=${nextBefore}` : "/api/sessions?limit=20";
  let page;
  try {
    page = await api(url);
  } catch (err) {
    list.replaceChildren(el("p", { class: "chart-empty" }, err.message));
    return;
  }
  if (!append) {
    list.replaceChildren();
    if (!page.sessions.length) {
      list.append(el("p", { class: "chart-empty" },
        "No sessions yet. Start the camera on the Monitor tab and they'll appear here."));
    } else {
      list.append(header());
    }
  }
  page.sessions.forEach((s) => list.append(sessionRow(s)));
  nextBefore = page.next_before;
  $("more-sessions").hidden = !nextBefore;
}

$("more-sessions").addEventListener("click", () => load(true));

export const sessionsView = { show: () => load(false) };
