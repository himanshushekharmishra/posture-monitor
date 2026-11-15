// Everything that writes to the page. No networking or camera code here.

const $ = (id) => document.getElementById(id);

const STATE_WORDS = {
  away: "Away",
  good: "Good posture",
  slouching: "Slouching",
  alerted: "Sit up",
};

const NOTES = {
  "no person": "No one in view",
  "low visibility": "Move so your ears and shoulders are in view",
  "not calibrated": "Calibrate to start scoring",
  "camera off": "Camera is off",
};

let threshold = 0.25;
let persistSeconds = 30;
let baseline = null;

export function setConfig(config) {
  threshold = config.slouch_threshold;
  persistSeconds = config.persist_seconds;
  // The meter shows 0..2x the threshold, so the alert line sits in the middle.
  $("meter-threshold").style.bottom = "50%";
}

export function setBaseline(b) {
  baseline = b;
}

export function setLinkStatus(status) {
  const el = $("link-status");
  el.dataset.state = status;
  el.textContent = {
    connecting: "Connecting to the server",
    online: "Connected",
    offline: "Server not reachable, retrying",
  }[status];
}

export function setHint(text, tone = "") {
  const el = $("hint");
  el.textContent = text;
  el.dataset.tone = tone;
}

export function setCameraOn(on) {
  $("stage").dataset.camera = on ? "on" : "off";
  $("camera-btn").textContent = on ? "Stop camera" : "Start camera";
}

export function setButtons({ canStart, canCalibrate, calibrating, canReportMissed }) {
  $("camera-btn").disabled = !canStart;
  $("calibrate-btn").disabled = !canCalibrate;
  $("calibrate-btn").textContent = calibrating ? "Cancel calibration" : "Calibrate";
  $("missed-btn").disabled = !canReportMissed;
}

export function setNotifyButton(permission) {
  const btn = $("notify-btn");
  if (!("Notification" in window)) {
    btn.hidden = true;
    return;
  }
  btn.disabled = permission !== "default";
  btn.textContent = {
    granted: "Notifications on",
    denied: "Notifications blocked in browser settings",
    default: "Turn on notifications",
  }[permission];
}

function formatSeconds(s) {
  if (s < 60) return `${Math.round(s)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

/** Render one "frame" message from the server. */
export function renderFrame(msg) {
  const readout = $("readout");
  readout.dataset.state = msg.state;
  $("state-word").textContent = STATE_WORDS[msg.state];
  // The header pill shows the state from every tab of the dashboard.
  const pill = $("live-pill");
  if (pill) {
    pill.dataset.state = msg.state;
    pill.textContent = STATE_WORDS[msg.state];
  }

  let detail = NOTES[msg.note] ?? "";
  if (!detail) {
    if (msg.state === "good") detail = "Keep it up";
    if (msg.state === "slouching")
      detail = `For ${formatSeconds(msg.slouch_seconds)}; alert after ${persistSeconds} s`;
    if (msg.state === "alerted") detail = `Slouching for ${formatSeconds(msg.slouch_seconds)}`;
  }
  $("state-detail").textContent = detail;

  const meter = $("score-meter");
  if (msg.score === null) {
    $("meter-fill").style.height = "0%";
    $("meter-value").textContent = "–";
    meter.setAttribute("aria-valuenow", "0");
  } else {
    const pct = Math.min(1, msg.score / (2 * threshold)) * 100;
    $("meter-fill").style.height = `calc(${pct}% - 6px)`;
    $("meter-value").textContent = msg.score.toFixed(2);
    meter.setAttribute("aria-valuenow", msg.score.toFixed(2));
  }
  renderFeatures(msg.features);
  $("alerts-today").textContent = msg.alerts_today;
}

function renderFeatures(f) {
  const set = (id, text, worse = false) => {
    const el = $(id);
    el.textContent = text;
    el.classList.toggle("worse", worse);
  };
  if (!f) {
    for (const id of ["f-neck", "f-lean", "f-shoulder", "f-head"]) set(id, "–");
    return;
  }
  const signed = (n) => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(0)}%`;
  $("features-note").textContent = baseline
    ? "Compared with your calibrated posture"
    : "Calibrate to compare with your good posture";
  if (baseline) {
    const neckPct = (f.neck_ratio / baseline.neck_ratio - 1) * 100;
    set("f-neck", signed(neckPct), neckPct < -10);
    const leanPct = (f.lean_ratio - 1) * 100;
    set("f-lean", signed(leanPct), leanPct > 10);
  } else {
    set("f-neck", f.neck_ratio.toFixed(2));
    set("f-lean", "–");
  }
  set("f-shoulder", `${f.shoulder_tilt.toFixed(1)}°`, Math.abs(f.shoulder_tilt) > 8);
  set("f-head", `${f.head_tilt.toFixed(1)}°`, Math.abs(f.head_tilt) > 10);
}

/** Reset the readout to "Away" when the camera is stopped. */
export function showCameraOff() {
  renderFrame({
    state: "away", score: null, slouch_seconds: 0, features: null, note: "camera off",
    alerts_today: Number($("alerts-today").textContent) || 0,
  });
}

let bannerTimer = null;

export function renderCalibration(cal) {
  const banner = $("calibration-banner");
  clearTimeout(bannerTimer); // a new status replaces any pending auto-hide
  if (!cal || cal.phase === "cancelled") {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  if (cal.phase === "countdown") {
    const startsIn = Math.max(0, cal.seconds_left - calibrationSeconds);
    banner.textContent = `Sit upright and face the camera. Recording starts in ${startsIn.toFixed(0)} s.`;
  } else if (cal.phase === "recording") {
    banner.textContent = `Recording your upright posture: ${cal.seconds_left.toFixed(0)} s left, hold still.`;
  } else {
    banner.textContent = cal.message;
    bannerTimer = setTimeout(() => (banner.hidden = true), 5000);
  }
}

let calibrationSeconds = 5;
export function setCalibrationSeconds(s) {
  calibrationSeconds = s;
}

export function showAlert(alert) {
  const box = $("alert-box");
  $("alert-text").textContent = alert.message;
  box.hidden = false;
  box.classList.remove("flash");
  void box.offsetWidth; // restart the animation
  box.classList.add("flash");
}

export function hideAlert() {
  $("alert-box").hidden = true;
}

export function renderStats(stats) {
  $("alerts-today").textContent = stats.alerts_today;
  const p = stats.labels.precision;
  $("precision").textContent = p === null ? "–" : `${Math.round(p * 100)}%`;
  $("missed").textContent = stats.labels.missed;
  // Session history has its own tab now (js/views/sessions.js).
}
