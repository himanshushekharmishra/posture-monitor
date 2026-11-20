// MediaPipe PoseLandmarker running in the browser (VIDEO mode).
// The model file comes from our own server (/model/...), the runtime from a CDN.
import {
  FaceLandmarker,
  FilesetResolver,
  PoseLandmarker,
} from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs";

const WASM_URL = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm";

/** [{start, end}] pairs of landmark indexes to draw the skeleton. */
export const POSE_CONNECTIONS = PoseLandmarker.POSE_CONNECTIONS;

/**
 * Load the pose model. Tries the GPU first and falls back to the CPU.
 * @returns {Promise<{delegate: string, detect: (video: HTMLVideoElement) => {landmarks: object[] | null, ms: number}, close: () => void}>}
 */
export function createPoseDetector(modelUrl) {
  return createDetector(PoseLandmarker, modelUrl, { numPoses: 1 }, (r) => r.landmarks?.[0]);
}

/**
 * Load the face mesh model (478 points). Only drawn in the page, never sent anywhere.
 * Same shape as createPoseDetector.
 */
export function createFaceDetector(modelUrl) {
  return createDetector(FaceLandmarker, modelUrl, { numFaces: 1 }, (r) => r.faceLandmarks?.[0]);
}

async function createDetector(Task, modelUrl, options, pick) {
  const fileset = await FilesetResolver.forVisionTasks(WASM_URL);
  const make = (delegate) =>
    Task.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: modelUrl, delegate },
      runningMode: "VIDEO",
      ...options,
    });

  let landmarker;
  let delegate = "GPU";
  try {
    landmarker = await make("GPU");
  } catch {
    delegate = "CPU";
    landmarker = await make("CPU");
  }

  let lastTs = -1;
  return {
    delegate,
    detect(video) {
      // VIDEO mode needs strictly increasing timestamps.
      let ts = performance.now();
      if (ts <= lastTs) ts = lastTs + 1;
      lastTs = ts;
      const start = performance.now();
      const result = landmarker.detectForVideo(video, ts);
      return { landmarks: pick(result) ?? null, ms: performance.now() - start };
    },
    close() {
      landmarker.close();
    },
  };
}
