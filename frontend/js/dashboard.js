// Dashboard shell: the dropdown menu and switching between tabs (#monitor, #meter, ...).
// The Monitor tab (main.js) keeps running while other tabs are open.
import { toast } from "./dom.js";
import { meterView } from "./views/meter.js";
import { profileView } from "./views/profile.js";
import { sessionsView } from "./views/sessions.js";
import { settingsView } from "./views/settings.js";

const VIEWS = {
  monitor: null,
  meter: meterView,
  sessions: sessionsView,
  profile: profileView,
  settings: settingsView,
};
const NAMES = { google: "Google", github: "GitHub", phone: "Phone" };
const body = document.body;
const menuBtn = document.getElementById("menu-btn");
const menuWrap = document.getElementById("nav-wrap");
const links = [...document.querySelectorAll(".nav-menu a")];

// ---------- tabs ----------
function show(name, focus = false) {
  if (!(name in VIEWS)) name = "monitor";
  for (const v of Object.keys(VIEWS)) {
    document.getElementById(`view-${v}`).hidden = v !== name;
  }
  for (const a of links) {
    if (a.dataset.view === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  const label = links.find((a) => a.dataset.view === name).textContent;
  document.getElementById("menu-label").textContent = label;
  document.title = name === "monitor" ? "Posture Monitor" : `${label} · Posture Monitor`;
  VIEWS[name]?.show();
  if (focus) document.getElementById("views").focus();
}

window.addEventListener("hashchange", () => {
  setMenu(false);
  show(location.hash.slice(1), true);
});

// ---------- dropdown menu ----------
const isOpen = () => menuBtn.getAttribute("aria-expanded") === "true";

function setMenu(open) {
  body.classList.toggle("nav-open", open);
  menuBtn.setAttribute("aria-expanded", String(open));
}

function focusLink(index) {
  links[(index + links.length) % links.length].focus();
}

menuBtn.addEventListener("click", () => setMenu(!isOpen()));

menuBtn.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    setMenu(true);
    focusLink(e.key === "ArrowDown" ? 0 : -1);
  }
});

// Clicking the page you're already on doesn't fire hashchange, so close here too.
for (const a of links) a.addEventListener("click", () => setMenu(false));

document.getElementById("nav-menu").addEventListener("keydown", (e) => {
  const i = links.indexOf(document.activeElement);
  if (e.key === "ArrowDown") { e.preventDefault(); focusLink(i + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); focusLink(i - 1); }
  else if (e.key === "Home") { e.preventDefault(); focusLink(0); }
  else if (e.key === "End") { e.preventDefault(); focusLink(-1); }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && isOpen()) {
    setMenu(false);
    menuBtn.focus();
  }
});

// Close when clicking or tabbing anywhere outside the menu.
document.addEventListener("pointerdown", (e) => {
  if (isOpen() && !menuWrap.contains(e.target)) setMenu(false);
});
menuWrap.addEventListener("focusout", (e) => {
  if (isOpen() && e.relatedTarget && !menuWrap.contains(e.relatedTarget)) setMenu(false);
});

// ---------- start ----------
setMenu(false);
const params = new URLSearchParams(location.search);
const linked = params.get("linked");
if (linked) {
  history.replaceState(null, "", `${location.pathname}#settings`);
  toast(`${NAMES[linked] || "Account"} connected.`);
  document.getElementById("trial-banner").hidden = true;
}
show(location.hash.slice(1) || "monitor");
