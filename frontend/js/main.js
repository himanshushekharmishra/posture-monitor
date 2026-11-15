// Wires camera -> pose model -> server -> page together.
//   camera frames stay here; only landmarks ([x, y, visibility] x 33) are sent.
import { PostureSocket } from "./connection.js";
import { createPoseDetector } from "./pose.js";
import { clearSkeleton, drawSkeleton } from "./skeleton.js";
import * as view from "./view.js";

const video = document.getElementById("video");
const overlay = document.getElementById("overlay");
const MODEL_URL = "/model/pose_landmarker.task";

const app = {
  config: null,
  detector: null,
  stream: null,
  calibrated: false,
  calibrating: false,
  alertPending: false,
  stateColor: "#7f8d95",
};

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
      app.calibrated = msg.calibrated;
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
      break;
  }
}

function handleFrame(msg) {
  view.renderFrame(msg);
  app.stateColor = getComputedStyle(document.getElementById("readout"))
    .getPropertyValue("--state").trim() || app.stateColor;

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
  new Notification(alert.title, { body: alert.message, tag: "posture" });
}

const socket = new PostureSocket(onMessage, (status) => {
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
  drawSkeleton(overlay, video, landmarks, app.config.min_visibility, app.stateColor);
  socket.send({
    type: "frame",
    landmarks: landmarks && landmarks.map((p) => [p.x, p.y, p.visibility ?? 1]),
    pose_ms: Math.round(ms * 10) / 10,
  });
}

async function startCamera() {
  try {
    app.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: "user" },
      audio: false,
    });
  } catch (err) {
    const reason = err.name === "NotAllowedError"
      ? "Camera access was blocked. Allow it in the address bar, then start the camera again."
      : `Couldn't open the camera (${err.name}). Close other apps using it and try again.`;
    view.setHint(reason, "error");
    return;
  }
  video.srcObject = app.stream;
  await video.play();
  view.setCameraOn(true);
  view.setHint(app.calibrated
    ? "Watching your posture. You can switch to another tab; alerts still arrive."
    : "Sit upright and press Calibrate so the app learns your good posture.");
  ticker.postMessage(1000 / app.config.process_fps);
}

function stopCamera() {
  ticker.postMessage(0);
  app.stream?.getTracks().forEach((t) => t.stop());
  app.stream = null;
  video.srcObject = null;
  clearSkeleton(overlay);
  view.setCameraOn(false);
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

// ---------- start up ----------
async function init() {
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
  refreshButtons();
  refreshStats();
  setInterval(refreshStats, 60_000);
}

init();
