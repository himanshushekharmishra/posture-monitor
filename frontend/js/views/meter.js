// Slouch meter: how often you slouch, today against your recent average,
// day by day and by hour of the day.
import { api } from "../api.js";
import { barChart, dataTable } from "../charts.js";
import { dayLabel, el, minutesText, perHourText } from "../dom.js";

const $ = (id) => document.getElementById(id);
let days = 14;
let last = null;

function hourLabel(h) {
  return `${String(h).padStart(2, "0")}:00`;
}

function hero(data) {
  const today = data.today;
  const avg = data.window.per_hour;
  const box = $("meter-hero");
  if (today.per_hour === null) {
    const recent = avg === null
      ? "Start the camera on the Monitor tab to begin."
      : `Your ${data.days}-day average is ${perHourText(avg)} slouches per hour. ` +
        "Start the camera on the Monitor tab to see today's.";
    box.replaceChildren(
      el("p", { class: "big empty" }, "Not monitored yet today"),
      el("p", { class: "compare" }, recent),
    );
    return;
  }
  let compare = `Your ${data.days}-day average is ${perHourText(avg)} per hour.`;
  if (avg !== null) {
    const diff = today.per_hour - avg;
    if (Math.abs(diff) < 0.1 * Math.max(avg, 0.5)) compare += " Today is about the same.";
    else compare += diff < 0 ? " Today is better than usual." : " Today is worse than usual.";
  }
  box.replaceChildren(
    el("p", { class: "big" }, perHourText(today.per_hour), el("small", {}, "slouches per hour today")),
    el("p", { class: "compare" }, compare),
  );
}

function figure(value, label) {
  return el("div", {}, el("span", { class: "value" }, value), el("span", { class: "label" }, label));
}

function render(data) {
  last = data;
  hero(data);
  $("meter-figures").replaceChildren(
    figure(String(data.today.slouches), "slouches today"),
    figure(minutesText(data.today.minutes), "monitored today"),
    figure(minutesText(data.today.slouch_minutes), "spent slouching today"),
    figure(String(data.window.slouches), `slouches in ${data.days} days`),
    figure(minutesText(data.window.minutes), `monitored in ${data.days} days`),
  );

  const daily = data.daily.map((d) => ({
    label: dayLabel(d.date),
    value: d.per_hour,
    tip: d.per_hour === null
      ? `${dayLabel(d.date)}: not monitored`
      : `${dayLabel(d.date)}: ${perHourText(d.per_hour)} per hour (${d.slouches} slouches in ${minutesText(d.minutes)})`,
  }));
  barChart($("chart-daily"), daily, {
    ariaLabel: `Slouches per hour of monitoring for each of the last ${data.days} days`,
    format: (v) => (v >= 10 ? v.toFixed(0) : v.toFixed(1)),
    emptyText: "No monitored days in this range yet.",
  });
  dataTable($("table-daily"), ["Day", "Slouches per hour", "Slouches", "Monitored"],
    data.daily.map((d) => [dayLabel(d.date), perHourText(d.per_hour), d.slouches, minutesText(d.minutes)]));

  const hours = data.by_hour.map((n, h) => ({
    label: hourLabel(h), value: n,
    tip: `${hourLabel(h)}–${hourLabel((h + 1) % 24)}: ${n} slouch${n === 1 ? "" : "es"}`,
  }));
  barChart($("chart-hours"), hours, {
    ariaLabel: `Slouches by hour of the day over the last ${data.days} days`,
    format: (v) => String(Math.round(v)),
    emptyText: "No slouches recorded in this range.",
  });
  dataTable($("table-hours"), ["Hour", "Slouches"],
    data.by_hour.map((n, h) => [`${hourLabel(h)}–${hourLabel((h + 1) % 24)}`, n]));
}

async function load() {
  try {
    render(await api(`/api/insights?days=${days}`));
  } catch (err) {
    $("meter-hero").replaceChildren(el("p", { class: "compare" }, err.message));
  }
}

document.querySelectorAll("#view-meter .range button").forEach((b) => {
  b.addEventListener("click", () => {
    days = Number(b.dataset.days);
    document.querySelectorAll("#view-meter .range button")
      .forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    load();
  });
});

document.querySelectorAll("#view-meter .table-toggle").forEach((b) => {
  b.addEventListener("click", () => {
    const table = $(`table-${b.dataset.table}`);
    table.hidden = !table.hidden;
    b.textContent = table.hidden ? "Show as table" : "Hide table";
  });
});

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (last && !$("view-meter").hidden) render(last);
  }, 150);
});

export const meterView = { show: load };
