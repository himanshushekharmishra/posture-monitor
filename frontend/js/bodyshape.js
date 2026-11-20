// The body's shape on a grid, from pose landmarks: capsules for limbs, neck and
//   the ear-shoulder bands, a slab for the torso, an ellipse for the head, filled
//   into grid cells. The hologram jitters the filled cells' centres and joins them
//   into its low-poly neck-and-shoulders mesh. Pure geometry, no drawing.

const DEPTH_SCALE = 0.5; // MediaPipe z is on roughly the x scale; flattened a little
const MAX_DEPTH = 0.25; // of the frame width, either side of the shoulders

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
const KEY_RADIUS = 0.14; // cells this close (x shoulder width) to an ear-shoulder line are "key"
const NECK_RADIUS = 0.17; // x shoulder width
const TRAPEZIUS_RADIUS = 0.07; // bands along the ear-shoulder lines, x shoulder width
const TORSO_DEPTH = 0.25; // bulge of the torso slab, x shoulder width
const TORSO_LENGTH = 1.4; // shoulder-to-hip length when the hips are out of frame

const clamp01 = (v) => Math.min(1, Math.max(0, v));

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
 * `columns` sets the grid: cells across the frame width.
 */
export function voxelize(points, width, height, minVisibility, columns) {
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
