// Dashboard shell: the side menu and switching between tabs (#monitor, #meter, ...).
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
const narrow = window.matchMedia("(max-width: 52rem)");

// ---------- tabs ----------
function show(name, focus = false) {
  if (!(name in VIEWS)) name = "monitor";
  for (const v of Object.keys(VIEWS)) {
    document.getElementById(`view-${v}`).hidden = v !== name;
  }
  document.querySelectorAll(".sidenav a").forEach((a) => {
    if (a.dataset.view === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  const label = document.querySelector(`.sidenav a[data-view="${name}"]`).textContent;
  document.title = name === "monitor" ? "Posture Monitor" : `${label} · Posture Monitor`;
  VIEWS[name]?.show();
  if (focus) document.getElementById("views").focus();
}

window.addEventListener("hashchange", () => {
  show(location.hash.slice(1), true);
  if (narrow.matches) setMenu(false);
});

// ---------- menu ----------
function readPref() {
  try {
    return localStorage.getItem("pm-nav") === "collapsed";
  } catch {
    return false;
  }
}

function writePref(collapsed) {
  try {
    localStorage.setItem("pm-nav", collapsed ? "collapsed" : "open");
  } catch {
    /* private mode: the menu just won't remember */
  }
}

function setMenu(open) {
  if (narrow.matches) {
    body.classList.toggle("nav-open", open);
  } else {
    body.classList.toggle("nav-collapsed", !open);
    writePref(!open);
  }
  menuBtn.setAttribute("aria-expanded", String(open));
}

function syncMenu() {
  body.classList.remove("nav-open");
  const open = narrow.matches ? false : !readPref();
  body.classList.toggle("nav-collapsed", !narrow.matches && !open);
  menuBtn.setAttribute("aria-expanded", String(open));
}

menuBtn.addEventListener("click", () => {
  setMenu(menuBtn.getAttribute("aria-expanded") !== "true");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && narrow.matches && body.classList.contains("nav-open")) {
    setMenu(false);
    menuBtn.focus();
  }
});
narrow.addEventListener("change", syncMenu);

// ---------- start ----------
syncMenu();
const params = new URLSearchParams(location.search);
const linked = params.get("linked");
if (linked) {
  history.replaceState(null, "", `${location.pathname}#settings`);
  toast(`${NAMES[linked] || "Account"} connected.`);
  document.getElementById("trial-banner").hidden = true;
}
show(location.hash.slice(1) || "monitor");
