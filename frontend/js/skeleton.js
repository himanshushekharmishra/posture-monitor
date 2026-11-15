// Draw the pose skeleton on the overlay canvas (same size as the video frame).
import { POSE_CONNECTIONS } from "./pose.js";

const FACE = new Set([0, 1, 2, 3, 4, 5, 6, 9, 10]); // drawn smaller
const KEY = new Set([7, 8, 11, 12]); // ears and shoulders: what the score uses

export function clearSkeleton(canvas) {
  canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
}

/**
 * @param {HTMLCanvasElement} canvas
 * @param {{x: number, y: number, visibility?: number}[] | null} landmarks
 * @param {number} minVisibility
 * @param {string} color  CSS colour for the posture state
 */
export function drawSkeleton(canvas, video, landmarks, minVisibility, color) {
  if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
  }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!landmarks) return;

  const w = canvas.width;
  const h = canvas.height;
  const seen = (p) => (p.visibility ?? 1) >= minVisibility;
  const scale = w / 640;

  ctx.lineCap = "round";
  ctx.strokeStyle = "rgba(255, 255, 255, 0.75)";
  ctx.lineWidth = 3 * scale;
  for (const { start, end } of POSE_CONNECTIONS) {
    const a = landmarks[start];
    const b = landmarks[end];
    if (!seen(a) || !seen(b)) continue;
    ctx.beginPath();
    ctx.moveTo(a.x * w, a.y * h);
    ctx.lineTo(b.x * w, b.y * h);
    ctx.stroke();
  }

  // The ear-to-shoulder lines carry the score, so draw them in the state colour.
  ctx.strokeStyle = color;
  ctx.lineWidth = 5 * scale;
  for (const [ear, shoulder] of [[7, 11], [8, 12]]) {
    const a = landmarks[ear];
    const b = landmarks[shoulder];
    if (!seen(a) || !seen(b)) continue;
    ctx.beginPath();
    ctx.moveTo(a.x * w, a.y * h);
    ctx.lineTo(b.x * w, b.y * h);
    ctx.stroke();
  }

  landmarks.forEach((p, i) => {
    if (!seen(p)) return;
    const r = (KEY.has(i) ? 7 : FACE.has(i) ? 2.5 : 4) * scale;
    ctx.beginPath();
    ctx.arc(p.x * w, p.y * h, r, 0, Math.PI * 2);
    ctx.fillStyle = KEY.has(i) ? color : "#ffffff";
    ctx.fill();
  });
}
