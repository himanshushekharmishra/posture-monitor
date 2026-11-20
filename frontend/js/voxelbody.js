// 3D voxel body over the camera view, drawn with WebGL2 and custom shaders.
//   Each animation frame the pose becomes simple solids (capsules for limbs, a slab
//   for the torso, an ellipsoid for the head), which are voxelized onto a grid and
//   drawn as instanced cubes. The ear-to-shoulder voxels (what the score uses) glow
//   in the state colour. While slouching the cubes crack apart, more as the alert
//   gets closer; an alert shatters the body, and sitting up reassembles it.
//   Only landmarks come in here; the camera image is never read.

const GRID_COLUMNS = 56; // voxels across the frame width
const DEPTH_SCALE = 0.5; // MediaPipe z is on roughly the x scale; flattened a little
const MAX_DEPTH = 0.25; // of the frame width, either side of the shoulders
const FOV_Y = (30 * Math.PI) / 180;
const FOLLOW_RATE = 12; // per second: how fast the drawn pose catches up with the detected one
const CRACK_RATE = 3; // per second
const SHATTER_SECONDS = 0.6;
const REASSEMBLE_SECONDS = 1.0;
const FADE_RATE = 4; // per second, when a person appears or leaves
const MAX_FPS = 30;
const BODY_COLOR = [0.86, 0.91, 0.96];
const OPACITY = 0.88;

// MediaPipe Pose landmark indexes
const NOSE = 0, L_EAR = 7, R_EAR = 8, L_SHOULDER = 11, R_SHOULDER = 12;
const L_HIP = 23, R_HIP = 24;
// [from, to, radius as a fraction of shoulder width]
const LIMBS = [
  [11, 13, 0.15], [13, 15, 0.12], [12, 14, 0.15], [14, 16, 0.12], // arms
  [15, 17, 0.07], [15, 19, 0.07], [16, 18, 0.07], [16, 20, 0.07], // hands
  [23, 25, 0.2], [25, 27, 0.15], [24, 26, 0.2], [26, 28, 0.15], // legs
  [11, 12, 0.13], // shoulder line, rounds off the top of the torso
];
const KEY_RADIUS = 0.14; // voxels this close (x shoulder width) to an ear-shoulder line glow
const NECK_RADIUS = 0.17; // x shoulder width
const TRAPEZIUS_RADIUS = 0.07; // bands along the ear-shoulder lines, x shoulder width
const TORSO_DEPTH = 0.25; // bulge of the torso slab, x shoulder width
const TORSO_LENGTH = 1.4; // shoulder-to-hip length when the hips are out of frame

const VERTEX_SHADER = `#version 300 es
precision highp float;
layout(location = 0) in vec3 aPos;     // unit cube corner, -0.5..0.5
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec3 aCenter;  // voxel centre; x/y in frame pixels, z toward the camera
layout(location = 3) in vec4 aSeed;    // xyz: random unit direction, w: random 0..1
layout(location = 4) in float aKey;    // 1 near the ear-shoulder lines
uniform mat4 uProj;
uniform float uFocal;    // camera distance: the z = 0 plane exactly fills the video frame
uniform float uCell;
uniform float uTime;
uniform float uCrack;    // 0..1 while slouching
uniform float uShatter;  // 0..1 after an alert
out vec3 vNormal;
out vec3 vLocal;
out float vKey;
out float vFade;

mat3 rotation(vec3 axis, float angle) {
  axis = normalize(axis);
  float s = sin(angle), c = cos(angle), oc = 1.0 - c;
  return mat3(
    oc * axis.x * axis.x + c, oc * axis.x * axis.y - axis.z * s, oc * axis.z * axis.x + axis.y * s,
    oc * axis.x * axis.y + axis.z * s, oc * axis.y * axis.y + c, oc * axis.y * axis.z - axis.x * s,
    oc * axis.z * axis.x - axis.y * s, oc * axis.y * axis.z + axis.x * s, oc * axis.z * axis.z + c);
}

void main() {
  float shatter = uShatter * uShatter * (3.0 - 2.0 * uShatter);
  float shiver = uCrack * (0.5 + 0.5 * sin(uTime * 9.0 + aSeed.w * 40.0));

  // Cracks: cubes shrink, so gaps open between them, and shiver in place.
  // Shatter: cubes fly out along their own direction, tumble, fall and drift.
  float size = uCell * (0.92 - 0.3 * uCrack) * (1.0 - 0.45 * shatter);
  vec3 drift = aSeed.xyz * uCell * (0.25 * shiver + 7.0 * shatter * (0.4 + aSeed.w));
  drift.y -= shatter * shatter * uCell * 10.0 * (0.5 + aSeed.w);
  drift += aSeed.zxy * uCell * 0.6 * shatter * sin(uTime * (1.0 + aSeed.w) + aSeed.w * 6.283);
  mat3 spin = rotation(aSeed.zxy + vec3(0.1), shatter * (2.0 + 4.0 * aSeed.w) + shiver * 0.25);

  vec3 center = aCenter + drift;
  // Scale x/y with depth so each voxel projects onto its spot in the video, whatever its z.
  float persp = (uFocal - center.z) / uFocal;
  vec3 world = vec3(center.xy * persp, center.z) + spin * aPos * size * persp;
  gl_Position = uProj * vec4(world - vec3(0.0, 0.0, uFocal), 1.0);

  vNormal = spin * aNormal;
  vLocal = aPos;
  vKey = aKey;
  vFade = 1.0 - 0.6 * shatter;
}`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;
in vec3 vNormal;
in vec3 vLocal;
in float vKey;
in float vFade;
uniform vec3 uStateColor;
uniform vec3 uBodyColor;
uniform float uOpacity;
out vec4 outColor;

void main() {
  vec3 n = normalize(vNormal);
  float diffuse = max(dot(n, normalize(vec3(-0.4, 0.6, 0.7))), 0.0);
  float rim = pow(1.0 - max(n.z, 0.0), 2.0);

  // Glowing cube edges. On a face one |coordinate| is 1; the middle-sized one
  // reaches 1 at an edge of that face.
  vec3 a = abs(vLocal) * 2.0;
  float middle = a.x + a.y + a.z - max(a.x, max(a.y, a.z)) - min(a.x, min(a.y, a.z));
  float w = fwidth(middle);
  float edge = smoothstep(0.86 - w, 0.97, middle);

  vec3 base = mix(uBodyColor, uStateColor, mix(0.25, 0.9, vKey));
  vec3 color = base * (0.35 + 0.75 * diffuse) + rim * 0.25 * uStateColor;
  color = mix(color, min(uStateColor * 1.3 + 0.15, vec3(1.0)), edge * 0.6);
  float alpha = uOpacity * vFade;
  outColor = vec4(color * alpha, alpha); // the canvas expects premultiplied alpha
}`;

// 36 vertices (position, normal) for a unit cube, 2 triangles per face.
function cubeVertices() {
  const faces = [
    [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [[-1, 0, 0], [0, 0, 1], [0, 1, 0]],
    [[0, 1, 0], [0, 0, 1], [1, 0, 0]], [[0, -1, 0], [1, 0, 0], [0, 0, 1]],
    [[0, 0, 1], [1, 0, 0], [0, 1, 0]], [[0, 0, -1], [0, 1, 0], [1, 0, 0]],
  ];
  const out = [];
  for (const [n, u, v] of faces) {
    const corner = (su, sv) => [0, 1, 2].map((i) => 0.5 * n[i] + 0.5 * su * u[i] + 0.5 * sv * v[i]);
    for (const [su, sv] of [[-1, -1], [1, -1], [1, 1], [-1, -1], [1, 1], [-1, 1]]) {
      out.push(...corner(su, sv), ...n);
    }
  }
  return new Float32Array(out);
}

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader));
  }
  return shader;
}

function perspective(fovY, aspect, near, far) {
  const f = 1 / Math.tan(fovY / 2);
  const nf = 1 / (near - far);
  return new Float32Array([
    f / aspect, 0, 0, 0,
    0, f, 0, 0,
    0, 0, (far + near) * nf, -1,
    0, 0, 2 * far * near * nf, 0,
  ]);
}

function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  return m ? [1, 2, 3].map((i) => parseInt(m[i], 16) / 255) : [0.5, 0.55, 0.6];
}

const clamp01 = (v) => Math.min(1, Math.max(0, v));
// Move `value` toward `target` at `rate` per second, frame-rate independent.
const approach = (value, target, rate, dt) => value + (target - value) * (1 - Math.exp(-rate * dt));
const step = (value, target, seconds, dt) =>
  value < target ? Math.min(target, value + dt / seconds) : Math.max(target, value - dt / seconds);

/** Distance from p to segment ab, and how far along it (0..1) the closest point is. */
function segment(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 > 0 ? clamp01(((px - ax) * dx + (py - ay) * dy) / len2) : 0;
  return [Math.hypot(px - ax - t * dx, py - ay - t * dy), t];
}

/** Signed distance from p to a convex polygon (negative inside). */
function polygonDistance(px, py, pts) {
  let d = Infinity;
  let inside = true;
  for (let i = 0; i < pts.length; i++) {
    const [ax, ay] = pts[i];
    const [bx, by] = pts[(i + 1) % pts.length];
    d = Math.min(d, segment(px, py, ax, ay, bx, by)[0]);
    if ((bx - ax) * (py - ay) - (by - ay) * (px - ax) < 0) inside = false;
  }
  // Points arrive in either winding; inside means on the same side of every edge.
  if (!inside) {
    inside = true;
    for (let i = 0; i < pts.length; i++) {
      const [ax, ay] = pts[i];
      const [bx, by] = pts[(i + 1) % pts.length];
      if ((bx - ax) * (py - ay) - (by - ay) * (px - ax) > 0) inside = false;
    }
  }
  return inside ? -d : d;
}

/**
 * Voxelize a pose given in normalized landmarks (0..1, y down). Returns the filled
 * cells as [x, y, z, key, column, row] in a Float32Array: x/y in frame pixels centred
 * on the frame with y up, z toward the camera relative to the shoulders, key 1 near
 * the ear-shoulder lines.
 * Exported for testing; the renderer calls it every animation frame.
 */
export function voxelize(points, width, height, minVisibility, columns = GRID_COLUMNS) {
  const cell = width / columns;
  const rows = Math.ceil(height / cell);
  const best = new Float32Array(columns * rows).fill(Infinity);
  const depth = new Float32Array(columns * rows);
  const seen = (i) => points[i] && (points[i].visibility ?? 1) >= minVisibility;
  const px = (i) => points[i].x * width;
  const py = (i) => points[i].y * height;
  const pz = (i) => -(points[i].z ?? 0) * width * DEPTH_SCALE;

  if (!seen(L_SHOULDER) || !seen(R_SHOULDER)) return { voxels: new Float32Array(0), cell };
  const shoulderWidth = Math.hypot(px(L_SHOULDER) - px(R_SHOULDER), py(L_SHOULDER) - py(R_SHOULDER));
  if (shoulderWidth <= 0) return { voxels: new Float32Array(0), cell };
  const zRef = (pz(L_SHOULDER) + pz(R_SHOULDER)) / 2;
  const maxDepth = MAX_DEPTH * width;
  const relZ = (z) => Math.max(-maxDepth, Math.min(maxDepth, z - zRef));

  // Write one solid: sdf(x, y) -> [signed distance, z of the surface there].
  const paint = (minX, minY, maxX, maxY, sdf) => {
    const i0 = Math.max(0, Math.floor(minX / cell)), i1 = Math.min(columns - 1, Math.floor(maxX / cell));
    const j0 = Math.max(0, Math.floor(minY / cell)), j1 = Math.min(rows - 1, Math.floor(maxY / cell));
    for (let j = j0; j <= j1; j++) {
      for (let i = i0; i <= i1; i++) {
        const [d, z] = sdf((i + 0.5) * cell, (j + 0.5) * cell);
        const k = j * columns + i;
        if (d < best[k]) {
          best[k] = d;
          depth[k] = z;
        }
      }
    }
  };
  const capsule = (ax, ay, az, bx, by, bz, r) => {
    paint(Math.min(ax, bx) - r, Math.min(ay, by) - r, Math.max(ax, bx) + r, Math.max(ay, by) + r,
      (x, y) => {
        const [d, t] = segment(x, y, ax, ay, bx, by);
        const bulge = Math.sqrt(Math.max(0, r * r - d * d));
        return [d - r, relZ(az + (bz - az) * t) + bulge];
      });
  };

  for (const [a, b, f] of LIMBS) {
    if (seen(a) && seen(b)) capsule(px(a), py(a), pz(a), px(b), py(b), pz(b), f * shoulderWidth);
  }

  // Neck, and bands along the ear-shoulder lines: the part of the body the score reads.
  const mid = (a, b, f) => (f(a) + f(b)) / 2;
  if (seen(L_EAR) && seen(R_EAR)) {
    capsule(mid(L_EAR, R_EAR, px), mid(L_EAR, R_EAR, py), mid(L_EAR, R_EAR, pz),
      mid(L_SHOULDER, R_SHOULDER, px), mid(L_SHOULDER, R_SHOULDER, py),
      mid(L_SHOULDER, R_SHOULDER, pz), NECK_RADIUS * shoulderWidth);
  }
  for (const [e, sh] of [[L_EAR, L_SHOULDER], [R_EAR, R_SHOULDER]]) {
    if (seen(e)) capsule(px(e), py(e), pz(e), px(sh), py(sh), pz(sh), TRAPEZIUS_RADIUS * shoulderWidth);
  }

  // Torso: shoulders down to the hips, or straight down when the hips are out of frame
  // (usual at a desk).
  const ls = [px(L_SHOULDER), py(L_SHOULDER)], rs = [px(R_SHOULDER), py(R_SHOULDER)];
  let down = [rs[1] - ls[1], ls[0] - rs[0]]; // perpendicular to the shoulder line
  if (down[1] < 0) down = [-down[0], -down[1]];
  const dl = Math.hypot(down[0], down[1]) || 1;
  const drop = TORSO_LENGTH * shoulderWidth / dl;
  const lh = seen(L_HIP) ? [px(L_HIP), py(L_HIP)] : [ls[0] + down[0] * drop, ls[1] + down[1] * drop];
  const rh = seen(R_HIP) ? [px(R_HIP), py(R_HIP)] : [rs[0] + down[0] * drop, rs[1] + down[1] * drop];
  const torso = [ls, rs, rh, lh];
  const tz = relZ(zRef) + TORSO_DEPTH * shoulderWidth;
  const xs = torso.map((p) => p[0]), ys = torso.map((p) => p[1]);
  paint(Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys), (x, y) => {
    const d = polygonDistance(x, y, torso);
    return [d, tz - TORSO_DEPTH * shoulderWidth * Math.exp(d / shoulderWidth * 4)];
  });

  // Head: an ellipse around the ears, a bit above them, turned with the ear line.
  const earsSeen = seen(L_EAR) && seen(R_EAR);
  if (earsSeen || seen(NOSE)) {
    const earDist = earsSeen ? Math.hypot(px(L_EAR) - px(R_EAR), py(L_EAR) - py(R_EAR)) : 0.45 * shoulderWidth;
    const cx = earsSeen ? (px(L_EAR) + px(R_EAR)) / 2 : px(NOSE);
    const cy = (earsSeen ? (py(L_EAR) + py(R_EAR)) / 2 : py(NOSE)) - 0.15 * earDist;
    const cz = relZ(earsSeen ? (pz(L_EAR) + pz(R_EAR)) / 2 : pz(NOSE));
    const angle = earsSeen ? Math.atan2(py(L_EAR) - py(R_EAR), px(L_EAR) - px(R_EAR)) : 0;
    const rx = 0.62 * earDist, ry = 0.8 * earDist;
    const cos = Math.cos(angle), sin = Math.sin(angle);
    const reach = Math.max(rx, ry);
    paint(cx - reach, cy - reach, cx + reach, cy + reach, (x, y) => {
      const u = ((x - cx) * cos + (y - cy) * sin) / rx;
      const v = (-(x - cx) * sin + (y - cy) * cos) / ry;
      const q = Math.hypot(u, v);
      return [(q - 1) * Math.min(rx, ry), cz + Math.sqrt(Math.max(0, 1 - q * q)) * rx];
    });
  }

  // Collect filled cells; mark the ones along the ear-shoulder lines.
  const keyLines = [[L_EAR, L_SHOULDER], [R_EAR, R_SHOULDER]].filter(([e, s]) => seen(e) && seen(s));
  const keyR = KEY_RADIUS * shoulderWidth;
  const out = [];
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < columns; i++) {
      const k = j * columns + i;
      if (best[k] >= 0) continue;
      const x = (i + 0.5) * cell, y = (j + 0.5) * cell;
      const key = keyLines.some(([e, s]) => segment(x, y, px(e), py(e), px(s), py(s))[0] < keyR);
      out.push(x - width / 2, height / 2 - y, depth[k], key ? 1 : 0, i, j);
    }
  }
  return { voxels: new Float32Array(out), cell };
}

// Stable per-cell random values, so fragments keep their direction from frame to frame.
function seedFor(i, j) {
  let h = Math.imul(i * 374761393 + j * 668265263, 1274126177) >>> 0;
  const next = () => {
    h = Math.imul(h ^ (h >>> 15), 2246822519) >>> 0;
    h = Math.imul(h ^ (h >>> 13), 3266489917) >>> 0;
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
  const theta = next() * Math.PI * 2;
  const cz = next() * 2 - 1;
  const r = Math.sqrt(1 - cz * cz);
  return [r * Math.cos(theta), r * Math.sin(theta) * 0.6 + 0.4, cz, next()];
}

/**
 * Create the renderer on a canvas laid over the video. Returns null when WebGL2
 * isn't available, so the caller can keep the 2D skeleton.
 */
export function createVoxelBody(canvas) {
  const gl = canvas.getContext("webgl2", { premultipliedAlpha: true, antialias: true });
  if (!gl) return null;

  let program;
  try {
    program = gl.createProgram();
    gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER));
    gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
  } catch (err) {
    console.warn("Voxel view unavailable:", err);
    return null;
  }
  const u = Object.fromEntries(
    ["uProj", "uFocal", "uCell", "uTime", "uCrack", "uShatter", "uStateColor", "uBodyColor", "uOpacity"]
      .map((name) => [name, gl.getUniformLocation(program, name)]));

  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const cube = cubeVertices();
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, cube, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 24, 0);
  gl.enableVertexAttribArray(1);
  gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 24, 12);

  const STRIDE = 8; // center xyz, seed xyzw, key
  const instanceBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, instanceBuffer);
  for (const [loc, size, offset] of [[2, 3, 0], [3, 4, 3], [4, 1, 7]]) {
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, size, gl.FLOAT, false, STRIDE * 4, offset * 4);
    gl.vertexAttribDivisor(loc, 1);
  }
  gl.bindVertexArray(null);
  let instances = new Float32Array(0);

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const seeds = new Map(); // "i,j" -> seed
  const state = {
    target: null, // latest detected landmarks
    drawn: null, // smoothed copy that is rendered
    frameW: 640,
    frameH: 480,
    minVisibility: 0.5,
    color: [0.5, 0.55, 0.6],
    crackTarget: 0,
    shatterTarget: 0,
    crack: 0,
    shatter: 0,
    presence: 0,
    running: false,
    lost: false,
    raf: 0,
    last: 0,
  };

  canvas.addEventListener("webglcontextlost", (e) => {
    e.preventDefault();
    state.lost = true;
    stop();
  });

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const k = Math.max(1, Math.min(2, (canvas.clientWidth * dpr) / state.frameW));
    const w = Math.round(state.frameW * k), h = Math.round(state.frameH * k);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
  }

  function smooth(dt) {
    if (!state.target) return;
    if (!state.drawn || state.drawn.length !== state.target.length) {
      state.drawn = state.target.map((p) => ({ ...p }));
      return;
    }
    state.drawn.forEach((p, i) => {
      const t = state.target[i];
      p.x = approach(p.x, t.x, FOLLOW_RATE, dt);
      p.y = approach(p.y, t.y, FOLLOW_RATE, dt);
      p.z = approach(p.z ?? 0, t.z ?? 0, FOLLOW_RATE, dt);
      p.visibility = t.visibility;
    });
  }

  function upload(voxels) {
    const count = voxels.length / 6;
    if (instances.length < count * STRIDE) instances = new Float32Array(count * STRIDE * 2);
    for (let n = 0; n < count; n++) {
      const v = n * 6, o = n * STRIDE;
      const i = voxels[v + 4], j = voxels[v + 5];
      const id = `${i},${j}`;
      let seed = seeds.get(id);
      if (!seed) seeds.set(id, (seed = seedFor(i, j)));
      instances[o] = voxels[v];
      instances[o + 1] = voxels[v + 1];
      instances[o + 2] = voxels[v + 2];
      instances.set(seed, o + 3);
      instances[o + 7] = voxels[v + 3];
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, instanceBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, instances.subarray(0, count * STRIDE), gl.DYNAMIC_DRAW);
    return count;
  }

  function frame(now) {
    if (!state.running) return;
    state.raf = requestAnimationFrame(frame);
    const dt = state.last ? (now - state.last) / 1000 : 0;
    if (state.last && dt < 1 / MAX_FPS - 0.002) return;
    state.last = now;

    const still = reducedMotion.matches;
    state.crack = approach(state.crack, still ? 0 : state.crackTarget, CRACK_RATE, dt);
    state.shatter = still ? 0 : step(state.shatter, state.shatterTarget,
      state.shatterTarget > state.shatter ? SHATTER_SECONDS : REASSEMBLE_SECONDS, dt);
    state.presence = approach(state.presence, state.target ? 1 : 0, FADE_RATE, dt);
    smooth(dt);

    resize();
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!state.drawn || state.presence < 0.01) return;

    const { voxels, cell } = voxelize(state.drawn, state.frameW, state.frameH, state.minVisibility);
    const count = upload(voxels);
    if (!count) return;

    const focal = state.frameH / 2 / Math.tan(FOV_Y / 2);
    gl.useProgram(program);
    gl.bindVertexArray(vao);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniformMatrix4fv(u.uProj, false, perspective(FOV_Y, state.frameW / state.frameH, 1, focal * 4));
    gl.uniform1f(u.uFocal, focal);
    gl.uniform1f(u.uCell, cell);
    gl.uniform1f(u.uTime, now / 1000);
    gl.uniform1f(u.uCrack, state.crack);
    gl.uniform1f(u.uShatter, state.shatter);
    gl.uniform3fv(u.uStateColor, state.color);
    gl.uniform3fv(u.uBodyColor, BODY_COLOR);
    gl.uniform1f(u.uOpacity, OPACITY * state.presence);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 36, count);
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
    state.target = state.drawn = null;
    state.presence = state.crack = state.shatter = 0;
    if (!state.lost) {
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    }
  }

  return {
    get available() {
      return !state.lost;
    },
    start,
    stop,
    /** Latest detection (landmarks with x, y, z, visibility), at the camera loop's rate. */
    setPose(landmarks, frameWidth, frameHeight, minVisibility) {
      state.target = landmarks;
      if (frameWidth && frameHeight) {
        state.frameW = frameWidth;
        state.frameH = frameHeight;
      }
      state.minVisibility = minVisibility;
    },
    /**
     * Posture from the server: cracks grow while slouching toward an alert, an alert
     * shatters the body, and any other state puts it back together.
     */
    setPosture(postureState, slouchSeconds, persistSeconds, colorHex) {
      state.color = hexToRgb(colorHex);
      state.shatterTarget = postureState === "alerted" ? 1 : 0;
      state.crackTarget = postureState === "slouching"
        ? 0.3 + 0.7 * clamp01(slouchSeconds / persistSeconds)
        : 0;
    },
  };
}
