// Wires camera -> pose model -> server -> page together.
//   camera frames stay here; only landmarks ([x, y, visibility] x 33) are sent.
import { api } from "./api.js";
import { PostureSocket } from "./connection.js";
import { createFaceDetector, createPoseDetector, FACE_TESSELATION } from "./pose.js";
import { createHologram } from "./hologram.js";
import { clearSkeleton, drawSkeleton } from "./skeleton.js";
import { createVoxelBody } from "./voxelbody.js";
import * as view from "./view.js";

const video = document.getElementById("video");
const overlay = document.getElementById("overlay");
const styleBtn = document.getElementById("style-btn");
const MODEL_URL = "/model/pose_landmarker.task";
const FACE_MODEL_URL = "/model/face_landmarker.task";
const STYLE_KEY = "posture.viewStyle";

const app = {
  config: null,
  detector: null,
  stream: null,
  calibrated: false,
  calibrating: false,
  alertPending: false,
  stateColor: "#7f8d95",
  face: null, // 478-point face mesh detector, for the hologram; drawn here, never sent
  renderers: {
    // null without WebGL2; "lines" (the 2D skeleton) always works
    hologram: createHologram(document.getElementById("hologram"),
      FACE_TESSELATION.map((c) => [c.start, c.end])),
    voxels: createVoxelBody(document.getElementById("voxels")),
  },
  style: readStyle(),
};

// ---------- view style: hologram, 3D voxel body or 2D lines ----------
const STYLES = ["hologram", "voxels", "lines"];
const STYLE_NAMES = { hologram: "Hologram", voxels: "3D blocks", lines: "Lines" };

function readStyle() {
  try {
    const saved = localStorage.getItem(STYLE_KEY);
    return STYLES.includes(saved) ? saved : "hologram";
  } catch {
    return "hologram"; // storage blocked (private window, site data off)
  }
}

const usable = (style) => style === "lines" || Boolean(app.renderers[style]?.available);

/** The style actually shown: the chosen one, or the next that works on this browser. */
function activeStyle() {
  const from = STYLES.indexOf(app.style);
  return [...STYLES.slice(from), ...STYLES.slice(0, from)].find(usable);
}

function renderStyleButton() {
  const styles = STYLES.filter(usable);
  styleBtn.hidden = styles.length < 2;
  styleBtn.textContent = `Style: ${STYLE_NAMES[activeStyle()]}`;
}

function applyStyle() {
  renderStyleButton();
  const active = activeStyle();
  for (const [style, renderer] of Object.entries(app.renderers)) {
    if (renderer && (style !== active || !app.stream)) renderer.stop();
  }
  if (!app.stream) return;
  if (active !== "lines") {
    clearSkeleton(overlay);
    app.renderers[active].start();
  }
}

function refreshButtons() {
  const online = socket.isOpen;
  view.setButtons({
    canStart: Boolean(app.detector),
    canCalibrate: online && Boolean(app.stream),
    calibrating: app.calibrating,
    canReportMissed: online && Boolean(app.stream) && app.calibrated,
  });
}

async function refreshStats() {
  try {
    const res = await fetch("/api/stats");
    if (res.ok) view.renderStats(await res.json());
  } catch {
    /* server down; the link status already says so */
  }
}

async function loadBaseline() {
  const res = await fetch("/api/baseline");
  view.setBaseline(res.ok ? await res.json() : null);
}

// ---------- server messages ----------
function onMessage(msg) {
  switch (msg.type) {
    case "hello":
      // A (re)connection starts a fresh server session: drop any state from the old one.
      app.calibrated = msg.calibrated;
      app.calibrating = false;
      app.alertPending = false;
      view.renderCalibration(null);
      view.hideAlert();
      if (msg.calibrated) loadBaseline();
      refreshButtons();
      break;
    case "frame":
      handleFrame(msg);
      break;
    case "calibration":
      app.calibrating = msg.phase === "countdown" || msg.phase === "recording";
      view.renderCalibration(msg);
      refreshButtons();
      break;
    case "labelled":
      app.alertPending = false;
      view.hideAlert();
      refreshStats();
      break;
    case "error":
      console.warn("Server:", msg.message);
      if (msg.message === "No alert to label yet") {
        app.alertPending = false; // the server no longer knows that alert
        view.hideAlert();
      }
      break;
  }
}

function handleFrame(msg) {
  view.renderFrame(msg);
  app.stateColor = getComputedStyle(document.getElementById("readout"))
    .getPropertyValue("--state").trim() || app.stateColor;
  for (const renderer of Object.values(app.renderers)) {
    renderer?.setPosture(msg.state, msg.slouch_seconds, app.config.persist_seconds, app.stateColor);
  }

  if (msg.calibration) {
    const phase = msg.calibration.phase;
    app.calibrating = phase === "countdown" || phase === "recording";
    view.renderCalibration(msg.calibration);
    if (phase === "done") loadBaseline();
  }
  if (msg.calibrated !== app.calibrated) {
    app.calibrated = msg.calibrated;
    if (msg.calibrated) loadBaseline();
  }
  if (msg.alert) {
    app.alertPending = true;
    view.showAlert(msg.alert);
    notify(msg.alert);
    refreshStats();
  }
  refreshButtons();
}

function notify(alert) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (document.visibilityState === "visible" && document.hasFocus()) return; // page shows it
  try {
    new Notification(alert.title, { body: alert.message, tag: "posture" });
  } catch (err) {
    // Android Chrome only allows notifications from a service worker; the page banner still shows.
    console.warn("Notification not shown:", err);
  }
}

const socket = new PostureSocket(onMessage, (status) => {
  if (status === "unauthorized") {
    stopCamera();
    location.replace("/login.html"); // the page sends expired trials on to #trial-ended
    return;
  }
  view.setLinkStatus(status);
  if (status === "online") refreshStats();
  refreshButtons();
});
socket.connect();

// ---------- camera loop ----------
// Browsers slow down timers in background tabs (down to once a minute in Chrome),
// which would stop monitoring when you switch tabs. Timers inside a worker aren't
// throttled that hard, so a tiny worker sets the pace.
const ticker = new Worker(URL.createObjectURL(new Blob(
  ["let t; onmessage = (e) => { clearInterval(t); if (e.data > 0) t = setInterval(() => postMessage(0), e.data); };"],
  { type: "text/javascript" },
)));
ticker.onmessage = tick;

function tick() {
  if (!app.stream || video.readyState < 2) return;
  const { landmarks, ms } = app.detector.detect(video);
  const style = activeStyle();
  if (style !== app.shownStyle) applyStyle(); // e.g. a GPU context was lost
  app.shownStyle = style;
  const minVis = app.config.min_visibility;
  if (style === "hologram") {
    const face = app.face ? app.face.detect(video).landmarks : null;
    app.renderers.hologram.setPose(landmarks, face, video.videoWidth, video.videoHeight, minVis);
  } else if (style === "voxels") {
    app.renderers.voxels.setPose(landmarks, video.videoWidth, video.videoHeight, minVis);
  } else {
    drawSkeleton(overlay, video, landmarks, minVis, app.stateColor);
  }
  socket.send({
    type: "frame",
    landmarks: landmarks && landmarks.map((p) => [p.x, p.y, p.visibility ?? 1]),
    pose_ms: Math.round(ms * 10) / 10,
  });
}

/** What went wrong with the camera, and what to do about it. */
function cameraErrorText(err) {
  switch (err.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Camera access is blocked for this site. Allow it with the camera icon in the " +
        "address bar, then start the camera again.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No camera found. Check it's connected and not switched off: many laptops have " +
        "a camera key or a privacy switch that disconnects it. Then start the camera again.";
    case "NotReadableError":
    case "AbortError":
      return "The camera is in use by another app (for example a video call). Close it, then " +
        "start the camera again.";
    default:
      return `Couldn't open the camera (${err.name}). Try again, or restart the browser.`;
  }
}

async function startCamera() {
  try {
    app.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: "user" },
      audio: false,
    });
  } catch (err) {
    view.setHint(cameraErrorText(err), "error");
    return;
  }
  video.srcObject = app.stream;
  await video.play();
  view.setCameraOn(true);
  view.setHint(app.calibrated
    ? "Watching your posture. You can switch to another tab; alerts still arrive."
    : "Sit upright and press Calibrate so the app learns your good posture.");
  ticker.postMessage(1000 / app.config.process_fps);
  applyStyle();
}

function stopCamera() {
  ticker.postMessage(0);
  if (app.calibrating) socket.send({ type: "cancel_calibration" }); // it needs frames to finish
  app.stream?.getTracks().forEach((t) => t.stop());
  app.stream = null;
  video.srcObject = null;
  clearSkeleton(overlay);
  applyStyle(); // no stream now: stops whichever renderer was running
  view.setCameraOn(false);
  view.showCameraOff(); // don't leave the last posture state on screen
  view.setHint("Camera off.");
}

// ---------- buttons ----------
document.getElementById("camera-btn").addEventListener("click", () => {
  if (app.stream) stopCamera();
  else startCamera().then(refreshButtons);
  refreshButtons();
});

document.getElementById("calibrate-btn").addEventListener("click", () => {
  socket.send({ type: app.calibrating ? "cancel_calibration" : "calibrate" });
});

styleBtn.addEventListener("click", () => {
  const styles = STYLES.filter(usable);
  app.style = styles[(styles.indexOf(activeStyle()) + 1) % styles.length];
  try {
    localStorage.setItem(STYLE_KEY, app.style);
  } catch {
    /* not remembered; still switches */
  }
  applyStyle();
});

document.getElementById("notify-btn").addEventListener("click", async () => {
  view.setNotifyButton(await Notification.requestPermission());
});

document.getElementById("alert-box").addEventListener("click", (e) => {
  const kind = e.target.closest("button")?.dataset.label;
  if (kind && app.alertPending) socket.send({ type: "label", kind });
});

document.getElementById("missed-btn").addEventListener("click", () => {
  socket.send({ type: "label", kind: "missed" });
});

// ---------- account ----------
async function loadAccount() {
  let me;
  try {
    me = await api("/api/auth/me");
  } catch (err) {
    if (err.status === 401) location.replace("/login.html");
    return false;
  }
  if (me.trial_expired) {
    location.replace("/login.html#trial-ended");
    return false;
  }
  document.getElementById("account-name").textContent = me.display_name || me.username;
  const banner = document.getElementById("trial-banner");
  if (me.is_guest) {
    const days = me.trial_days_left;
    banner.textContent = `Guest trial: ${days} day${days === 1 ? "" : "s"} left.`;
    banner.hidden = false;
  }
  return true;
}

document.getElementById("logout-btn").addEventListener("click", async () => {
  stopCamera();
  try {
    await api("/api/auth/logout", {});
  } finally {
    location.replace("/login.html");
  }
});

// ---------- start up ----------
async function init() {
  if (!(await loadAccount())) return;
  if ("Notification" in window) view.setNotifyButton(Notification.permission);
  else view.setNotifyButton("unsupported");
  try {
    app.config = await (await fetch("/api/config")).json();
  } catch {
    view.setHint("Can't reach the server. Start it with: python -m backend", "error");
    return;
  }
  view.setConfig(app.config);
  view.setCalibrationSeconds(app.config.calibration_seconds);

  if (!navigator.mediaDevices?.getUserMedia) {
    view.setHint("This browser can't use the camera here. Open the page at http://127.0.0.1 or over HTTPS.", "error");
    return;
  }
  try {
    app.detector = await createPoseDetector(MODEL_URL);
  } catch (err) {
    console.error(err);
    view.setHint("The pose model didn't load. Check that models/pose_landmarker_lite.task exists and the page can reach cdn.jsdelivr.net.", "error");
    return;
  }
  view.setHint(`Pose model ready (${app.detector.delegate}). Start the camera when you're at your desk.`);
  renderStyleButton();
  // The face mesh only adds detail to the hologram, so it loads in the background and
  // its absence (an old setup without the face model) isn't an error.
  createFaceDetector(FACE_MODEL_URL)
    .then((face) => (app.face = face))
    .catch((err) => console.warn("Face mesh unavailable (run scripts\\setup.ps1):", err));
  refreshButtons();
  refreshStats();
  setInterval(refreshStats, 60_000);
}

init();
