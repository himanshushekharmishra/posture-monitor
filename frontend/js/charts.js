// Single-series SVG bar chart: thin bars with rounded tops anchored to the baseline,
// three recessive grid lines, selective x labels, and a hover/focus tooltip.
// Built with DOM calls (no innerHTML) so it works under the page's strict CSP.
import { el } from "./dom.js";

const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};

function niceMax(v) {
  if (!(v > 0)) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * mag).find((n) => n >= v);
}

/** Path for a bar with 4px rounded top corners and a square base. */
function barPath(x, y, w, h) {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}` +
    `Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/**
 * @param {HTMLElement} container
 * @param {{label: string, value: number|null, tip: string}[]} items  null = no data
 * @param {{format?: (v: number) => string, height?: number, ariaLabel: string}} opts
 */
export function barChart(container, items, opts) {
  container.replaceChildren();
  if (!items.some((d) => d.value !== null && d.value > 0)) {
    container.append(el("p", { class: "chart-empty" }, opts.emptyText || "No data yet."));
    return;
  }
  const format = opts.format || ((v) => String(v));
  const width = Math.max(280, container.clientWidth || 640);
  const height = opts.height || 190;
  const m = { top: 10, right: 4, bottom: 26, left: 34 };
  const plotW = width - m.left - m.right;
  const plotH = height - m.top - m.bottom;
  const max = niceMax(Math.max(...items.map((d) => d.value || 0)));
  const band = plotW / items.length;
  const barW = Math.max(3, Math.min(28, band - 2)); // >= 2px gap between bars
  const y = (v) => m.top + plotH - (v / max) * plotH;

  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": opts.ariaLabel });
  const grid = svgEl("g", { class: "grid" });
  const axis = svgEl("g", { class: "axis" });
  for (const f of [0, 0.5, 1]) {
    const v = max * f;
    grid.append(svgEl("line", { x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }));
    const t = svgEl("text", { x: m.left - 6, y: y(v) + 4, "text-anchor": "end" });
    t.textContent = format(v);
    axis.append(t);
  }
  svg.append(grid, axis);

  const tip = el("div", { class: "chart-tip", hidden: true });
  const show = (d, cx, bar) => {
    tip.textContent = d.tip;
    tip.hidden = false;
    tip.style.left = `${(cx / width) * 100}%`;
    tip.style.top = `${(Math.min(y(d.value || 0), m.top + plotH - 8) / height) * 100}%`;
    container.querySelectorAll(".bar.active").forEach((b) => b.classList.remove("active"));
    bar?.classList.add("active");
  };
  const hide = () => {
    tip.hidden = true;
    container.querySelectorAll(".bar.active").forEach((b) => b.classList.remove("active"));
  };

  const every = Math.max(1, Math.ceil(items.length / Math.max(1, Math.floor(plotW / 44))));
  items.forEach((d, i) => {
    const cx = m.left + band * i + band / 2;
    // Hit target: the whole column, bigger than the bar.
    const hit = svgEl("rect", { class: "hit", x: m.left + band * i, y: m.top, width: band,
      height: plotH, tabindex: "0", "aria-label": d.tip });
    let bar = null;
    if (d.value !== null && d.value > 0) {
      bar = svgEl("path", { class: "bar", d: barPath(cx - barW / 2, y(d.value), barW,
        m.top + plotH - y(d.value)) });
    } else if (d.value === null) {
      const t = svgEl("text", { class: "empty-day", x: cx, y: m.top + plotH - 4,
        "text-anchor": "middle" });
      t.textContent = "–";
      bar = t;
    }
    hit.addEventListener("mouseenter", () => show(d, cx, bar));
    hit.addEventListener("focus", () => show(d, cx, bar));
    hit.addEventListener("mouseleave", hide);
    hit.addEventListener("blur", hide);
    svg.append(hit);
    if (bar) svg.append(bar);
    if (i % every === 0) { // evenly spaced labels; forcing the last one made them collide
      const t = svgEl("text", { x: cx, y: height - 8, "text-anchor": "middle" });
      t.textContent = d.label;
      axis.append(t);
    }
  });
  container.append(svg, tip);
}

/** A plain table version of the same data, for screen readers and exact numbers. */
export function dataTable(container, headers, rows) {
  container.replaceChildren(el("table", {},
    el("thead", {}, el("tr", {}, headers.map((h) => el("th", { scope: "col" }, h)))),
    el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, c))))),
  ));
}
