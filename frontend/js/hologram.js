// Holographic wireframe over the camera view (WebGL2, own GLSL shaders).
//   Face: a sparse low-poly mesh over 31 key points of the 478-point face mesh
//   (hairline, brows, eyes, nose, cheeks, mouth, jaw): thin light lines with
//   glowing nodes at the corners. Neck and shoulders: a low-poly
//   wireframe made by jittering points over the body's silhouette and joining
//   neighbours into triangles. Plus corner brackets that track the face, a
//   sweeping scan line and drifting particles that link up when close.
//   Light blue while posture is good, amber jitter while slouching; an alert rips the
//   mesh apart (stretched edges fade out) and sitting up pulls it back together.
//   Only landmarks come in here; the camera image is never read.
import { voxelize } from "./voxelbody.js";

const BODY_COLUMNS = 24; // body mesh points across the frame width
const FOLLOW_RATE = 14; // per second: how fast the drawn points catch up with detections
const CRACK_RATE = 3;
const SHATTER_SECONDS = 0.7;
const REASSEMBLE_SECONDS = 1.2;
const FADE_RATE = 4;
const MAX_FPS = 30;
const PARTICLES = 70;
const PARTICLE_LINK = 0.07; // link particles closer than this, x frame width
const BRACKET_PAD = 0.35; // around the face box
// Per posture state: [line colour, glow colour]. Lines and node centres are a light
// shade; the glow around nodes is deeper, like the reference look.
const PALETTE = {
  // The glow is still light: over a bright camera image a dark tint would darken it.
  good: [[0.82, 0.94, 1.0], [0.42, 0.74, 1.0]], // light blue, blue glow
  slouching: [[1.0, 0.9, 0.7], [1.0, 0.74, 0.35]],
  alerted: [[1.0, 0.75, 0.72], [1.0, 0.46, 0.42]],
  away: [[0.85, 0.9, 0.98], [0.6, 0.72, 0.95]],
};

// The face's low-poly mesh: edges between 31 face-mesh landmarks (hairline 109 10 338;
// brows 70 107 9 336 300; eye corners 33 133 362 263; face sides 234 454; nose 6 1 98
// 327; cheeks 205 425; mouth 61 0 291 17; jaw and chin 132 361 58 288 148 377 152).
// Delaunay triangulation of those points on MediaPipe's canonical face, computed once,
// so the mesh keeps its shape from frame to frame.
const FACE_EDGES = [
  [0, 1], [0, 17], [0, 61], [0, 98], [0, 291], [0, 327], [1, 6], [1, 98], [1, 133], [1, 327],
  [1, 362], [6, 9], [6, 107], [6, 133], [6, 336], [6, 362], [9, 10], [9, 107], [9, 336],
  [10, 107], [10, 109], [10, 336], [10, 338], [17, 61], [17, 148], [17, 152], [17, 291],
  [17, 377], [33, 70], [33, 107], [33, 133], [33, 205], [33, 234], [58, 61], [58, 132],
  [58, 148], [58, 205], [61, 98], [61, 148], [61, 205], [70, 107], [70, 109], [70, 234],
  [98, 133], [98, 205], [107, 109], [107, 133], [132, 205], [132, 234], [133, 205],
  [148, 152], [152, 377], [205, 234], [263, 300], [263, 336], [263, 362], [263, 425],
  [263, 454], [288, 291], [288, 361], [288, 377], [288, 425], [291, 327], [291, 377],
  [291, 425], [300, 336], [300, 338], [300, 454], [327, 362], [327, 425], [336, 338],
  [336, 362], [361, 425], [361, 454], [362, 425], [425, 454],
];
const FACE_NODES = [...new Set(FACE_EDGES.flat())];
const L_EAR = 7, R_EAR = 8, L_SHOULDER = 11, R_SHOULDER = 12;
const SKELETON = [[L_EAR, L_SHOULDER], [R_EAR, R_SHOULDER], [L_SHOULDER, R_SHOULDER],
  [11, 13], [13, 15], [12, 14], [14, 16]];
const KEY_JOINTS = [L_EAR, R_EAR, L_SHOULDER, R_SHOULDER, 13, 14];

// Shared by both shaders: where a point moves when the body cracks or shatters.
const SCATTER = `
uniform float uTime;
uniform float uCrack;
uniform float uShatter;
uniform float uScatter;  // how far shattered points fly, in frame pixels
float ease(float x) { return x * x * (3.0 - 2.0 * x); }
vec2 scatter(float seed) {
  if (seed < 0.0) return vec2(0.0);  // brackets and particles stay put
  float a = seed * 43.98;
  vec2 dir = vec2(cos(a), sin(a));
  float s = ease(uShatter);
  vec2 crack = dir * uCrack * 3.0 * sin(uTime * 9.0 + seed * 50.0);
  float r = uScatter * (0.35 + fract(seed * 13.7));
  vec2 burst = dir * s * r + vec2(0.0, 1.0) * s * s * r * 0.7;  // y is down: they fall
  burst += vec2(sin(uTime * 1.3 + seed * 20.0), cos(uTime * 1.1 + seed * 30.0)) * s * 8.0;
  return crack + burst;
}
// A bright band sweeping down the frame, like a scanner.
float scan(float y, float frameH) {
  float pos = mod(uTime * 0.3, 1.4) * frameH - 0.2 * frameH;
  float d = (y - pos) / (frameH * 0.035);
  return exp(-d * d);
}`;

const LINE_VS = `#version 300 es
precision highp float;
layout(location = 0) in vec2 aCorner;  // x: 0..1 along the line, y: -1..1 across
layout(location = 1) in vec4 aEnds;    // a.xy, b.xy in frame pixels, y down
layout(location = 2) in vec4 aStyle;   // seed a, seed b, brightness, core width (px)
uniform vec2 uFrame;
${SCATTER}
out float vAlong;
out float vAcross;
out float vLen;
out float vWidth;
out float vGlow;
out float vBright;
out float vY;

void main() {
  vec2 a = aEnds.xy + scatter(aStyle.x);
  vec2 b = aEnds.zw + scatter(aStyle.y);
  vec2 d = b - a;
  float len = max(length(d), 1e-3);
  vec2 t = d / len;
  vec2 n = vec2(-t.y, t.x);
  float glow = aStyle.w * 1.5 + 0.6;
  float hw = aStyle.w * 0.5 + glow * 2.0;  // quad half-width, room for the glow
  vec2 p = mix(a, b, aCorner.x) + t * (aCorner.x * 2.0 - 1.0) * hw + n * aCorner.y * hw;
  gl_Position = vec4(p.x / uFrame.x * 2.0 - 1.0, 1.0 - p.y / uFrame.y * 2.0, 0.0, 1.0);

  // A torn edge (stretched well past its rest length) fades away.
  float rest = length(aEnds.zw - aEnds.xy);
  float stretch = rest > 0.0 ? len / rest : 1.0;
  float torn = clamp(1.0 - (stretch - 1.0) * 0.8, 0.0, 1.0);
  vAlong = mix(-hw, len + hw, aCorner.x);
  vAcross = aCorner.y * hw;
  vLen = len;
  vWidth = aStyle.w;
  vGlow = glow;
  vBright = aStyle.z * torn * (1.0 - 0.45 * ease(uShatter)) * (1.0 + scan(p.y, uFrame.y) * 0.9);
  vY = p.y;
}`;

// How much the hologram covers the camera image under it (0 = pure added light).
// Kept below the darkest glow channel, so lines only ever brighten the video, also
// over a light background; full coverage would let a blue glow darken it.
const COVER_GLSL = "const float COVER = 0.3;";

const LINE_FS = `#version 300 es
precision highp float;
${COVER_GLSL}
in float vAlong;
in float vAcross;
in float vLen;
in float vWidth;
in float vGlow;
in float vBright;
in float vY;
uniform vec3 uColor;
uniform vec3 uGlow;
uniform float uPixel;  // frame pixels per canvas pixel, for anti-aliasing
out vec4 outColor;

void main() {
  float beyond = max(max(-vAlong, vAlong - vLen), 0.0);
  float d = length(vec2(beyond, vAcross));
  float core = 1.0 - smoothstep(vWidth * 0.5 - uPixel, vWidth * 0.5 + uPixel, d);
  float glow = exp(-(d * d) / (vGlow * vGlow));
  vec3 color = (uColor * core + uGlow * glow * 0.25) * vBright;
  float a = clamp((core + glow * 0.25) * vBright, 0.0, 1.0);
  outColor = vec4(color, a * COVER);
}`;

const POINT_VS = `#version 300 es
precision highp float;
layout(location = 0) in vec2 aCorner;  // -1..1
layout(location = 1) in vec4 aPoint;   // x, y (frame pixels), seed, brightness
layout(location = 2) in float aRadius;
uniform vec2 uFrame;
${SCATTER}
out vec2 vOffset;
out float vRadius;
out float vBright;

void main() {
  vec2 c = aPoint.xy + scatter(aPoint.z);
  float extent = aRadius * 4.0;
  vec2 p = c + aCorner * extent;
  gl_Position = vec4(p.x / uFrame.x * 2.0 - 1.0, 1.0 - p.y / uFrame.y * 2.0, 0.0, 1.0);
  float seed = abs(aPoint.z);
  float twinkle = 0.75 + 0.25 * sin(uTime * 3.0 + seed * 40.0);
  vOffset = aCorner * extent;
  vRadius = aRadius;
  vBright = aPoint.w * twinkle * (1.0 + scan(c.y, uFrame.y) * 1.2);
}`;

const POINT_FS = `#version 300 es
precision highp float;
${COVER_GLSL}
in vec2 vOffset;
in float vRadius;
in float vBright;
uniform vec3 uColor;
uniform vec3 uGlow;
uniform float uPixel;
out vec4 outColor;

void main() {
  float d = length(vOffset);
  float core = 1.0 - smoothstep(vRadius - uPixel, vRadius + uPixel, d);
  float halo = exp(-(d * d) / (vRadius * vRadius * 5.0));
  vec3 color = (mix(uColor, vec3(1.0), 0.6) * core + uGlow * halo * 0.9) * vBright;
  outColor = vec4(color, clamp((core + halo * 0.9) * vBright, 0.0, 1.0) * COVER);
}`;

function program(gl, vsSource, fsSource) {
  const compile = (type, source) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, source);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  };
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl.VERTEX_SHADER, vsSource));
  gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fsSource));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const uniforms = {};
  for (let i = 0; i < gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i++) {
    const { name } = gl.getActiveUniform(p, i);
    uniforms[name] = gl.getUniformLocation(p, name);
  }
  return { p, u: uniforms };
}

/** A VAO with a static corner quad (location 0) and an instance buffer laid out by `attrs`. */
function instancedVao(gl, corners, attrs, stride) {
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(corners), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  for (const [loc, size, offset] of attrs) {
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride * 4, offset * 4);
    gl.vertexAttribDivisor(loc, 1);
  }
  gl.bindVertexArray(null);
  return { vao, buffer };
}

const clamp01 = (v) => Math.min(1, Math.max(0, v));
const approach = (value, target, rate, dt) => value + (target - value) * (1 - Math.exp(-rate * dt));
const step = (value, target, seconds, dt) =>
  value < target ? Math.min(target, value + dt / seconds) : Math.max(target, value - dt / seconds);

// Deterministic 0..1 random from an integer, so mesh points keep their jitter and
// their shatter direction from frame to frame.
function hash01(n) {
  let h = Math.imul(n ^ 0x9e3779b9, 0x85ebca6b) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

/** Growable Float32Array for per-frame instance data. */
class Batch {
  constructor(stride) {
    this.stride = stride;
    this.data = new Float32Array(stride * 1024);
    this.count = 0;
  }
  push(...values) {
    if ((this.count + 1) * this.stride > this.data.length) {
      const bigger = new Float32Array(this.data.length * 2);
      bigger.set(this.data);
      this.data = bigger;
    }
    this.data.set(values, this.count * this.stride);
    this.count++;
  }
}

/**
 * Build this frame's lines and points (frame pixels, y down).
 * Exported for testing; the renderer calls it every animation frame.
 */
export function buildHologram(pose, face, width, height, minVisibility, particles = []) {
  const lines = new Batch(8); // ax, ay, bx, by, seedA, seedB, brightness, width
  const points = new Batch(5); // x, y, seed, brightness, radius

  // Face mesh
  let faceBox = null;
  if (face) {
    const fx = (i) => face[i].x * width;
    const fy = (i) => face[i].y * height;
    const near = (i) => 0.75 + 0.25 * clamp01(-(face[i].z ?? 0) * 6); // nearer is brighter
    const seed = (i) => hash01(i + 1000);
    for (const [a, b] of FACE_EDGES) {
      lines.push(fx(a), fy(a), fx(b), fy(b), seed(a), seed(b), 1.15 * (near(a) + near(b)) / 2, 0.7);
    }
    for (const i of FACE_NODES) points.push(fx(i), fy(i), seed(i), 1.3 * near(i), 1.7);

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const p of face) {
      minX = Math.min(minX, p.x * width); maxX = Math.max(maxX, p.x * width);
      minY = Math.min(minY, p.y * height); maxY = Math.max(maxY, p.y * height);
    }
    faceBox = { minX, minY, maxX, maxY };
  }

  // Body: jittered points over the silhouette, joined into triangles.
  if (pose) {
    const { voxels, cell } = voxelize(pose, width, height, minVisibility, BODY_COLUMNS);
    // With a face mesh, the body mesh stops at the chin so the two don't overlap.
    const inFace = (x, y) => {
      if (!faceBox) return false;
      const margin = (faceBox.maxX - faceBox.minX) * 0.2;
      return y < faceBox.maxY && x > faceBox.minX - margin && x < faceBox.maxX + margin;
    };
    const verts = new Map(); // "i,j" -> [x, y, seed, key]
    for (let n = 0; n < voxels.length / 6; n++) {
      const v = n * 6;
      const i = voxels[v + 4], j = voxels[v + 5];
      const id = j * 4096 + i;
      const x = voxels[v] + width / 2 + (hash01(id * 2) - 0.5) * cell * 0.7;
      const y = height / 2 - voxels[v + 1] + (hash01(id * 2 + 1) - 0.5) * cell * 0.7;
      if (inFace(x, y)) continue;
      verts.set(`${i},${j}`, [x, y, hash01(id + 7), voxels[v + 3]]);
    }
    const link = (p, q) => {
      if (!p || !q) return;
      const key = Math.max(p[3], q[3]);
      lines.push(p[0], p[1], q[0], q[1], p[2], q[2], 0.3 + 0.4 * key, 0.35 + 0.2 * key);
    };
    for (const [id, p] of verts) {
      const [i, j] = id.split(",").map(Number);
      link(p, verts.get(`${i + 1},${j}`));
      link(p, verts.get(`${i},${j + 1}`));
      // One diagonal per grid square, picked at random, makes it read as triangles.
      if (hash01(j * 4096 + i + 99) < 0.5) link(p, verts.get(`${i + 1},${j + 1}`));
      else link(verts.get(`${i + 1},${j}`), verts.get(`${i},${j + 1}`));
      points.push(p[0], p[1], p[2], 0.35 + 0.4 * p[3], 0.9);
    }

    // The lines the score is built on, drawn bright over the mesh.
    const seen = (i) => pose[i] && (pose[i].visibility ?? 1) >= minVisibility;
    const px = (i) => pose[i].x * width, py = (i) => pose[i].y * height;
    for (const [a, b] of SKELETON) {
      if (seen(a) && seen(b)) {
        lines.push(px(a), py(a), px(b), py(b), hash01(a + 500), hash01(b + 500), 0.9, 0.7);
      }
    }
    for (const i of KEY_JOINTS) if (seen(i)) points.push(px(i), py(i), hash01(i + 500), 1.3, 2.2);

    if (!faceBox && seen(L_EAR) && seen(R_EAR)) {
      const half = Math.abs(px(L_EAR) - px(R_EAR)) * 0.75;
      const cx = (px(L_EAR) + px(R_EAR)) / 2, cy = (py(L_EAR) + py(R_EAR)) / 2;
      faceBox = { minX: cx - half, maxX: cx + half, minY: cy - half * 1.3, maxY: cy + half * 1.2 };
    }
  }

  // Scanner brackets around the face.
  if (faceBox) {
    const w = faceBox.maxX - faceBox.minX, h = faceBox.maxY - faceBox.minY;
    const x0 = faceBox.minX - w * BRACKET_PAD, x1 = faceBox.maxX + w * BRACKET_PAD;
    const y0 = faceBox.minY - h * BRACKET_PAD * 0.6, y1 = faceBox.maxY + h * BRACKET_PAD * 0.6;
    const len = Math.min(x1 - x0, y1 - y0) * 0.18;
    for (const [x, y, dx, dy] of [[x0, y0, 1, 1], [x1, y0, -1, 1], [x0, y1, 1, -1], [x1, y1, -1, -1]]) {
      lines.push(x, y, x + dx * len, y, -1, -1, 0.7, 0.9);
      lines.push(x, y, x, y + dy * len, -1, -1, 0.7, 0.9);
    }
  }

  // Drifting particles, linked when close.
  const linkDist = PARTICLE_LINK * width;
  let links = 0;
  for (let a = 0; a < particles.length; a++) {
    const p = particles[a];
    points.push(p.x, p.y, -1 - p.seed, 0.55 * p.alpha, p.r);
    for (let b = a + 1; b < particles.length && links < 140; b++) {
      const q = particles[b];
      const d = Math.hypot(p.x - q.x, p.y - q.y);
      if (d < linkDist) {
        lines.push(p.x, p.y, q.x, q.y, -1, -1, 0.35 * (1 - d / linkDist) * Math.min(p.alpha, q.alpha), 0.25);
        links++;
      }
    }
  }
  return { lines, points };
}

/** Particles drift up through the lower part of the frame and wrap around. */
function makeParticles(width, height) {
  return Array.from({ length: PARTICLES }, (_, k) => ({
    x: hash01(k * 3) * width,
    y: height * (0.45 + 0.6 * hash01(k * 3 + 1)),
    vx: (hash01(k * 3 + 2) - 0.5) * 6,
    vy: -(4 + 10 * hash01(k * 5)),
    r: 0.7 + 1.4 * hash01(k * 7),
    seed: hash01(k * 11),
    alpha: 1,
  }));
}

function moveParticles(particles, width, height, dt) {
  for (const p of particles) {
    p.x += p.vx * dt;
    p.y += p.vy * dt;
    if (p.y < height * 0.4) p.y = height * 1.05;
    if (p.x < 0) p.x += width;
    if (p.x > width) p.x -= width;
    // Fade in from the bottom edge, out toward the middle of the frame.
    p.alpha = clamp01((p.y - height * 0.4) / (height * 0.25)) * clamp01((height * 1.05 - p.y) / (height * 0.1));
  }
}

/** Create the renderer on a canvas laid over the video. Returns null without WebGL2. */
export function createHologram(canvas) {
  const gl = canvas.getContext("webgl2", { premultipliedAlpha: true, antialias: false });
  if (!gl) return null;
  let lineProg, pointProg;
  try {
    lineProg = program(gl, LINE_VS, LINE_FS);
    pointProg = program(gl, POINT_VS, POINT_FS);
  } catch (err) {
    console.warn("Hologram view unavailable:", err);
    return null;
  }
  const lineQuad = [0, -1, 1, -1, 1, 1, 0, -1, 1, 1, 0, 1];
  const pointQuad = [-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1];
  const lineVao = instancedVao(gl, lineQuad, [[1, 4, 0], [2, 4, 4]], 8);
  const pointVao = instancedVao(gl, pointQuad, [[1, 4, 0], [2, 1, 4]], 5);

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const state = {
    pose: null, face: null, // latest detections
    drawnPose: null, drawnFace: null, // smoothed copies that are drawn
    frameW: 640, frameH: 480, minVisibility: 0.5,
    colors: PALETTE.away.map((c) => c.slice()), targetColors: PALETTE.away,
    crackTarget: 0, shatterTarget: 0, crack: 0, shatter: 0, presence: 0,
    particles: makeParticles(640, 480),
    running: false, lost: false, raf: 0, last: 0,
  };

  canvas.addEventListener("webglcontextlost", (e) => {
    e.preventDefault();
    state.lost = true;
    stop();
  });

  function follow(drawn, target, dt) {
    if (!target) return drawn;
    if (!drawn || drawn.length !== target.length) return target.map((p) => ({ ...p }));
    drawn.forEach((p, i) => {
      const t = target[i];
      p.x = approach(p.x, t.x, FOLLOW_RATE, dt);
      p.y = approach(p.y, t.y, FOLLOW_RATE, dt);
      p.z = approach(p.z ?? 0, t.z ?? 0, FOLLOW_RATE, dt);
      p.visibility = t.visibility;
    });
    return drawn;
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const k = Math.max(1, Math.min(2, (canvas.clientWidth * dpr) / state.frameW));
    const w = Math.round(state.frameW * k), h = Math.round(state.frameH * k);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
  }

  function draw(prog, vao, batch, now) {
    if (!batch.count) return;
    gl.useProgram(prog.p);
    gl.bindVertexArray(vao.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, vao.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, batch.data.subarray(0, batch.count * batch.stride), gl.DYNAMIC_DRAW);
    const u = prog.u;
    gl.uniform2f(u.uFrame, state.frameW, state.frameH);
    gl.uniform1f(u.uTime, (now / 1000) % 1000);
    gl.uniform1f(u.uCrack, state.crack);
    gl.uniform1f(u.uShatter, state.shatter);
    gl.uniform1f(u.uScatter, state.frameW * 0.3);
    gl.uniform3fv(u.uColor, state.colors[0].map((c) => c * state.presence));
    gl.uniform3fv(u.uGlow, state.colors[1].map((c) => c * state.presence));
    gl.uniform1f(u.uPixel, state.frameW / canvas.width);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 6, batch.count);
  }

  function frame(now) {
    if (!state.running) return;
    state.raf = requestAnimationFrame(frame);
    const dt = state.last ? Math.min(0.1, (now - state.last) / 1000) : 0;
    if (state.last && dt < 1 / MAX_FPS - 0.002) return;
    state.last = now;

    const still = reducedMotion.matches;
    state.crack = approach(state.crack, still ? 0 : state.crackTarget, CRACK_RATE, dt);
    state.shatter = still ? 0 : step(state.shatter, state.shatterTarget,
      state.shatterTarget > state.shatter ? SHATTER_SECONDS : REASSEMBLE_SECONDS, dt);
    state.presence = approach(state.presence, state.pose || state.face ? 1 : 0, FADE_RATE, dt);
    state.colors = state.colors.map((tone, t) =>
      tone.map((c, i) => approach(c, state.targetColors[t][i], 4, dt)));
    state.drawnPose = follow(state.drawnPose, state.pose, dt);
    state.drawnFace = state.face ? follow(state.drawnFace, state.face, dt) : null;
    if (!still) moveParticles(state.particles, state.frameW, state.frameH, dt);

    resize();
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (state.presence < 0.01) return;

    const { lines, points } = buildHologram(state.drawnPose, state.drawnFace, state.frameW,
      state.frameH, state.minVisibility, state.particles);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE); // light adds up, like a hologram
    draw(lineProg, lineVao, lines, now);
    draw(pointProg, pointVao, points, now);
    gl.bindVertexArray(null);
  }

  function start() {
    if (state.running || state.lost) return;
    state.running = true;
    state.last = 0;
    state.raf = requestAnimationFrame(frame);
  }

  function stop() {
    state.running = false;
    cancelAnimationFrame(state.raf);
    state.pose = state.face = state.drawnPose = state.drawnFace = null;
    state.presence = state.crack = state.shatter = 0;
    if (!state.lost) {
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
    }
  }

  return {
    get available() {
      return !state.lost;
    },
    start,
    stop,
    /** Latest detections: pose (33 points) and face mesh (478 points), either may be null. */
    setPose(pose, face, frameWidth, frameHeight, minVisibility) {
      state.pose = pose;
      state.face = face;
      if (frameWidth && frameHeight && (frameWidth !== state.frameW || frameHeight !== state.frameH)) {
        state.frameW = frameWidth;
        state.frameH = frameHeight;
        state.particles = makeParticles(frameWidth, frameHeight);
      }
      state.minVisibility = minVisibility;
    },
    /** Same meaning as the voxel body's: crack while slouching, shatter on an alert. */
    setPosture(postureState, slouchSeconds, persistSeconds) {
      state.targetColors = PALETTE[postureState] ?? PALETTE.away;
      state.shatterTarget = postureState === "alerted" ? 1 : 0;
      state.crackTarget = postureState === "slouching"
        ? 0.3 + 0.7 * clamp01(slouchSeconds / persistSeconds)
        : 0;
    },
  };
}
