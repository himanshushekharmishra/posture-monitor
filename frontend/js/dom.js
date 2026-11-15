// Tiny DOM and formatting helpers shared by the dashboard pages.
// el() only ever sets text, never HTML, so data from the server can't inject markup.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function minutesText(min) {
  if (min === null || min === undefined) return "–";
  if (min < 1) return `${Math.round(min * 60)} s`;
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function perHourText(v) {
  return v === null || v === undefined ? "–" : v.toFixed(1);
}

export function percentText(share) {
  return share === null || share === undefined ? "–" : `${Math.round(share * 100)}%`;
}

export function dayLabel(isoDate) {
  const d = new Date(`${isoDate}T12:00:00`);
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function dateTimeLabel(iso) {
  return new Date(iso).toLocaleString([], {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

export function timeLabel(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function setStatus(form, text, tone = "") {
  const s = form.querySelector(".form-status");
  s.textContent = text;
  s.dataset.tone = tone;
}

export function toast(text) {
  const t = document.getElementById("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 4000);
}
