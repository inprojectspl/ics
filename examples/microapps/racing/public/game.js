// Race Track: one closed track, three laps against the clock, results
// through the app's own endpoints. Three.js is bundled (no CDN on app origins).
import * as THREE from "./three.module.min.js";

const $ = (id) => document.getElementById(id);
const LAPS = 3;
const ROAD_W = 14;
const SAMPLES = 1000;
const SECTORS = 4;
const MAX_ON = 55;      // m/s on asphalt
const MAX_OFF = 20;     // m/s on grass
const ACCEL = 20;
const BRAKE = 38;
const REVERSE = -8;

// ---------- track ----------
const POINTS = [[0, 0], [120, 0], [175, 35], [170, 110], [110, 135], [70, 95], [20, 110],
  [-50, 150], [-130, 120], [-160, 45], [-120, -15], [-60, -25]];
const curve = new THREE.CatmullRomCurve3(POINTS.map(([x, z]) => new THREE.Vector3(x, 0, z)), true, "centripetal");
const pts = curve.getSpacedPoints(SAMPLES).slice(0, SAMPLES);
const tangents = pts.map((_, i) => pts[(i + 1) % SAMPLES].clone().sub(pts[(i - 1 + SAMPLES) % SAMPLES]).normalize());
const normals = tangents.map((t) => new THREE.Vector3(-t.z, 0, t.x));

const renderer = new THREE.WebGLRenderer({ canvas: $("scene"), antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x87b7e8);
scene.fog = new THREE.Fog(0x87b7e8, 160, 520);
const camera = new THREE.PerspectiveCamera(65, 1, 0.5, 1200);

scene.add(new THREE.HemisphereLight(0xdfefff, 0x4c6b2f, 0.9));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(80, 140, 40);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
Object.assign(sun.shadow.camera, { left: -40, right: 40, top: 40, bottom: -40, near: 10, far: 400 });
scene.add(sun, sun.target);

const ground = new THREE.Mesh(new THREE.PlaneGeometry(1400, 1400), new THREE.MeshLambertMaterial({ color: 0x4f8a3a }));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

/** A strip along the track between two signed offsets from the centre line. */
function strip(from, to, y, colorAt) {
  const pos = [], col = [], idx = [];
  for (let i = 0; i <= SAMPLES; i++) {
    const k = i % SAMPLES;
    const a = pts[k].clone().addScaledVector(normals[k], from);
    const b = pts[k].clone().addScaledVector(normals[k], to);
    pos.push(a.x, y, a.z, b.x, y, b.z);
    const c = colorAt(i);
    col.push(c.r, c.g, c.b, c.r, c.g, c.b);
    if (i < SAMPLES) { const j = i * 2; idx.push(j, j + 1, j + 2, j + 1, j + 3, j + 2); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  const m = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide }));
  m.receiveShadow = true;
  scene.add(m);
}
const asphalt = new THREE.Color(0x3a3d44), red = new THREE.Color(0xd63a2f), white = new THREE.Color(0xf4f4f4), dash = new THREE.Color(0xe8e8e8);
strip(-ROAD_W / 2, ROAD_W / 2, 0.02, () => asphalt);
strip(-ROAD_W / 2 - 1.2, -ROAD_W / 2, 0.03, (i) => (Math.floor(i / 6) % 2 ? red : white));
strip(ROAD_W / 2, ROAD_W / 2 + 1.2, 0.03, (i) => (Math.floor(i / 6) % 2 ? red : white));
strip(-0.15, 0.15, 0.04, (i) => (Math.floor(i / 8) % 2 ? dash : asphalt));

// Start line: a chequered band across the road at sample 0.
{
  const tiles = new THREE.Group();
  const geo = new THREE.PlaneGeometry(1, 1);
  const mats = [new THREE.MeshBasicMaterial({ color: 0x111111 }), new THREE.MeshBasicMaterial({ color: 0xffffff })];
  for (let r = 0; r < 2; r++) for (let c = 0; c < ROAD_W; c++) {
    const t = new THREE.Mesh(geo, mats[(r + c) % 2]);
    t.rotation.x = -Math.PI / 2;
    t.position.set(c - ROAD_W / 2 + 0.5, 0.05, r - 1);
    tiles.add(t);
  }
  tiles.position.copy(pts[0]);
  tiles.rotation.y = Math.atan2(tangents[0].x, tangents[0].z);
  scene.add(tiles);
  const gantry = new THREE.Mesh(new THREE.BoxGeometry(ROAD_W + 4, 1.2, 0.6), new THREE.MeshLambertMaterial({ color: 0xffb020 }));
  gantry.position.copy(pts[0]).add(new THREE.Vector3(0, 6, 0));
  gantry.rotation.y = tiles.rotation.y;
  scene.add(gantry);
  for (const s of [-1, 1]) {
    const pole = new THREE.Mesh(new THREE.BoxGeometry(0.5, 6, 0.5), new THREE.MeshLambertMaterial({ color: 0x555555 }));
    pole.position.copy(pts[0]).addScaledVector(normals[0], s * (ROAD_W / 2 + 2)).add(new THREE.Vector3(0, 3, 0));
    scene.add(pole);
  }
}

/** Index of the nearest track sample, searched around a hint first. */
function nearest(p, hint) {
  let best = -1, bestD = Infinity;
  const scan = (from, to) => {
    for (let i = from; i <= to; i++) {
      const k = ((i % SAMPLES) + SAMPLES) % SAMPLES;
      const d = (pts[k].x - p.x) ** 2 + (pts[k].z - p.z) ** 2;
      if (d < bestD) { bestD = d; best = k; }
    }
  };
  if (hint >= 0) scan(hint - 40, hint + 40);
  if (hint < 0 || bestD > 30 * 30) scan(0, SAMPLES - 1);
  return { index: best, dist: Math.sqrt(bestD) };
}

// Trees, kept off the road; one instanced mesh each for trunks and crowns.
{
  const n = 160, rnd = mulberry(7);
  const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.4, 0.5, 3), new THREE.MeshLambertMaterial({ color: 0x6b4a2b }), n);
  const crowns = new THREE.InstancedMesh(new THREE.ConeGeometry(2.6, 7, 7), new THREE.MeshLambertMaterial({ color: 0x2f6b2a }), n);
  const m = new THREE.Matrix4();
  let placed = 0;
  while (placed < n) {
    const p = new THREE.Vector3(rnd() * 460 - 220, 0, rnd() * 340 - 120);
    if (nearest(p, -1).dist < ROAD_W + 6) continue;
    const s = 0.7 + rnd() * 0.8;
    m.compose(p.clone().setY(1.5 * s), new THREE.Quaternion(), new THREE.Vector3(s, s, s));
    trunks.setMatrixAt(placed, m);
    m.compose(p.clone().setY((3 + 3.5) * s), new THREE.Quaternion(), new THREE.Vector3(s, s, s));
    crowns.setMatrixAt(placed, m);
    placed++;
  }
  crowns.castShadow = true;
  scene.add(trunks, crowns);
}

function mulberry(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------- car ----------
const car = new THREE.Group();
{
  const paint = new THREE.MeshLambertMaterial({ color: 0xe8432e });
  const dark = new THREE.MeshLambertMaterial({ color: 0x1b1f27 });
  const glass = new THREE.MeshLambertMaterial({ color: 0x9fd0ff });
  const body = new THREE.Mesh(new THREE.BoxGeometry(2, 0.6, 4.2), paint);
  body.position.y = 0.6;
  const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.55, 2), glass);
  cabin.position.set(0, 1.15, -0.2);
  const wing = new THREE.Mesh(new THREE.BoxGeometry(2.1, 0.1, 0.5), dark);
  wing.position.set(0, 1.25, -2);
  car.add(body, cabin, wing);
  for (const [x, z] of [[-1, 1.4], [1, 1.4], [-1, -1.4], [1, -1.4]]) {
    const w = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.35, 14), dark);
    w.rotation.z = Math.PI / 2;
    w.position.set(x, 0.42, z);
    car.add(w);
  }
  car.traverse((o) => { o.castShadow = true; });
  scene.add(car);
}

// ---------- state ----------
const keys = { left: false, right: false, gas: false, brake: false };
const state = {
  phase: "menu",          // menu | countdown | race | done
  speed: 0, heading: 0, pos: new THREE.Vector3(),
  idx: 0, sector: 0, visited: 0, lap: 1, raceStart: 0, lapStart: 0, laps: [], best: null,
};

function placeAtStart() {
  // Far enough past the line that the chase camera clears the start gantry.
  const i = 24;
  state.pos.copy(pts[i]).addScaledVector(normals[i], -3);
  state.heading = Math.atan2(tangents[i].x, tangents[i].z);
  Object.assign(state, { speed: 0, idx: i, sector: 0, visited: 0, lap: 1, laps: [] });
  syncCar(0);
  camPos.copy(state.pos).add(new THREE.Vector3(-Math.sin(state.heading) * 12, 5, -Math.cos(state.heading) * 12));
}

const camPos = new THREE.Vector3();
function syncCar(dt) {
  car.position.copy(state.pos);
  car.rotation.y = state.heading;
  const back = new THREE.Vector3(-Math.sin(state.heading), 0, -Math.cos(state.heading));
  const want = state.pos.clone().addScaledVector(back, 10 + Math.abs(state.speed) * 0.06).add(new THREE.Vector3(0, 4.2, 0));
  camPos.lerp(want, dt ? Math.min(1, dt * 5) : 1);
  camera.position.copy(camPos);
  camera.lookAt(state.pos.clone().add(new THREE.Vector3(0, 1.4, 0)).addScaledVector(back, -6));
  sun.position.copy(state.pos).add(new THREE.Vector3(60, 120, 30));
  sun.target.position.copy(state.pos);
}

function step(dt, now) {
  const { index, dist } = nearest(state.pos, state.idx);
  state.idx = index;
  const onTrack = dist <= ROAD_W / 2 + 1.2;
  const max = onTrack ? MAX_ON : MAX_OFF;
  if (state.phase === "race") {
    if (keys.gas) state.speed += ACCEL * dt;
    if (keys.brake) state.speed -= (state.speed > 0 ? BRAKE : ACCEL * 0.5) * dt;
  }
  state.speed -= state.speed * (onTrack ? 0.12 : 0.9) * dt;
  if (!keys.gas && !keys.brake) state.speed -= Math.sign(state.speed) * Math.min(Math.abs(state.speed), 3 * dt);
  if (state.speed > max) state.speed = Math.max(max, state.speed - 45 * dt);
  state.speed = Math.max(REVERSE, state.speed);
  const steer = (keys.left ? 1 : 0) - (keys.right ? 1 : 0);
  const grip = Math.min(1, Math.abs(state.speed) / 12) * Math.sign(state.speed);
  state.heading += steer * 2.1 * (1 - 0.4 * Math.min(1, Math.abs(state.speed) / MAX_ON)) * grip * dt;
  state.pos.x += Math.sin(state.heading) * state.speed * dt;
  state.pos.z += Math.cos(state.heading) * state.speed * dt;
  state.pos.x = THREE.MathUtils.clamp(state.pos.x, -600, 600);
  state.pos.z = THREE.MathUtils.clamp(state.pos.z, -600, 600);

  // Laps: the sectors must be passed in order, so a shortcut or driving
  // backwards over the line does not count.
  if (state.phase === "race") {
    const sector = Math.floor((index / SAMPLES) * SECTORS);
    if (sector === (state.sector + 1) % SECTORS) {
      state.sector = sector;
      if (sector === 0 && state.visited === SECTORS - 1) lapDone(now);
      else state.visited = sector === 0 ? 0 : state.visited + 1;
    }
  }
  $("offtrack").hidden = onTrack || state.phase !== "race";
}

function lapDone(now) {
  const ms = Math.round(now - state.lapStart);
  state.laps.push(ms);
  state.lapStart = now;
  state.visited = 0;
  state.best = state.best === null ? ms : Math.min(state.best, ms);
  $("last").textContent = fmt(ms);
  $("best").textContent = fmt(state.best);
  if (state.laps.length === LAPS) finish();
  else state.lap++;
}

// ---------- loop ----------
let last = performance.now();
function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  if (state.phase === "race" || state.phase === "done") step(dt, now);
  syncCar(dt);
  if (state.phase === "race") {
    $("time").textContent = fmt(now - state.raceStart);
    $("lap").textContent = `${state.lap}/${LAPS}`;
  }
  $("speed").textContent = String(Math.round(Math.abs(state.speed) * 3.6));
  drawMap();
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

// ---------- minimap ----------
const map = $("map"), mctx = map.getContext("2d");
const bounds = pts.reduce((b, p) => ({ minX: Math.min(b.minX, p.x), maxX: Math.max(b.maxX, p.x), minZ: Math.min(b.minZ, p.z), maxZ: Math.max(b.maxZ, p.z) }),
  { minX: Infinity, maxX: -Infinity, minZ: Infinity, maxZ: -Infinity });
function toMap(p) {
  const s = Math.min((map.width - 20) / (bounds.maxX - bounds.minX), (map.height - 20) / (bounds.maxZ - bounds.minZ));
  return [10 + (p.x - bounds.minX) * s, map.height - 10 - (p.z - bounds.minZ) * s];
}
function drawMap() {
  mctx.clearRect(0, 0, map.width, map.height);
  mctx.lineWidth = 5;
  mctx.strokeStyle = "#ffffff55";
  mctx.beginPath();
  pts.forEach((p, i) => { const [x, y] = toMap(p); if (i) mctx.lineTo(x, y); else mctx.moveTo(x, y); });
  mctx.closePath();
  mctx.stroke();
  const [sx, sy] = toMap(pts[0]);
  mctx.fillStyle = "#ffffff";
  mctx.fillRect(sx - 3, sy - 3, 6, 6);
  const [cx, cy] = toMap(state.pos);
  mctx.fillStyle = "#ffb020";
  mctx.beginPath();
  mctx.arc(cx, cy, 5, 0, Math.PI * 2);
  mctx.fill();
}

// ---------- input ----------
const KEYMAP = { ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right", ArrowUp: "gas", KeyW: "gas", ArrowDown: "brake", KeyS: "brake", Space: "brake" };
addEventListener("keydown", (e) => { if (KEYMAP[e.code] && !e.target.closest?.("input")) { keys[KEYMAP[e.code]] = true; e.preventDefault(); } });
addEventListener("keyup", (e) => { if (KEYMAP[e.code]) keys[KEYMAP[e.code]] = false; });
if (matchMedia("(pointer: coarse)").matches) $("touch").hidden = false;
for (const b of document.querySelectorAll("[data-key]")) {
  const set = (on) => (e) => { e.preventDefault(); keys[b.dataset.key] = on; b.classList.toggle("on", on); };
  b.addEventListener("pointerdown", set(true));
  for (const ev of ["pointerup", "pointercancel", "pointerleave"]) b.addEventListener(ev, set(false));
}

// ---------- race flow ----------
const fmt = (ms) => { const m = Math.floor(ms / 60000), s = (ms % 60000) / 1000; return `${m}:${s.toFixed(3).padStart(6, "0")}`; };

function start() {
  placeAtStart();
  state.best = null;
  $("last").textContent = "-";
  $("best").textContent = "-";
  $("time").textContent = fmt(0);
  $("lap").textContent = `1/${LAPS}`;
  $("overlay").hidden = true;
  state.phase = "countdown";
  const cd = $("countdown");
  cd.hidden = false;
  let n = 3;
  cd.textContent = String(n);
  const tick = setInterval(() => {
    n--;
    if (n > 0) { cd.textContent = String(n); return; }
    clearInterval(tick);
    cd.textContent = "START!";
    setTimeout(() => { cd.hidden = true; }, 700);
    state.phase = "race";
    state.raceStart = state.lapStart = performance.now();
  }, 800);
}

function finish() {
  state.phase = "done";
  const total = state.laps.reduce((a, b) => a + b, 0);
  $("ov-title").textContent = `Finish! ${fmt(total)}`;
  $("ov-text").textContent = "Save your result or race again.";
  $("laps").replaceChildren(
    ...state.laps.map((ms, i) => row(`Lap ${i + 1}`, fmt(ms) + (ms === state.best ? "  ★" : ""))),
    row("Total", fmt(total), "total"),
  );
  $("result").hidden = false;
  $("saved").textContent = "";
  $("save").hidden = !session;
  $("start").textContent = "Race again";
  $("overlay").hidden = false;
  $("player").focus();
}

function row(label, value, cls) {
  const tr = document.createElement("tr");
  if (cls) tr.className = cls;
  for (const t of [label, value]) { const td = document.createElement("td"); td.textContent = t; tr.append(td); }
  return tr;
}

$("start").addEventListener("click", start);
$("save").addEventListener("submit", async (e) => {
  e.preventDefault();
  const player = $("player").value.trim();
  if (!player) return;
  const btn = e.submitter;
  btn.disabled = true;
  try {
    localStorage.setItem("race-track.player", player);
  } catch { /* private mode */ }
  try {
    const r = await ics.call("POST", "/v1/custom/results", { body: { player, laps: state.laps } });
    $("saved").textContent = `Saved: place ${r.rank} on the board.`;
    $("save").hidden = true;
    myResult = r.id;
    await loadTop();
  } catch (err) {
    $("saved").textContent = `The result was not saved (${err.code || err.status}).`;
  } finally {
    btn.disabled = false;
  }
});

// ---------- results ----------
let session = null, myResult = null;
const judge = () => session?.roles?.includes("judge");

async function loadTop() {
  const { items, best_lap } = await ics.call("GET", "/v1/custom/top");
  $("top").replaceChildren(...items.map((r) => {
    const li = document.createElement("li");
    if (r.id === myResult) li.className = "me";
    li.append(r.player);
    const t = document.createElement("span");
    t.className = "t";
    t.textContent = fmt(r.total_ms);
    li.append(t);
    if (judge()) {
      const del = document.createElement("button");
      del.type = "button";
      del.textContent = "remove";
      del.title = `Remove the result of ${r.player}`;
      del.onclick = async () => {
        if (!confirm(`Remove the result of ${r.player} (${fmt(r.total_ms)})?`)) return;
        await ics.collection("results").remove(r.id, r.revision);
        await loadTop();
      };
      li.append(del);
    }
    return li;
  }));
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "muted empty";
    li.textContent = "Nobody has finished a race yet.";
    $("top").replaceChildren(li);
  }
  $("fastest").textContent = best_lap ? `Fastest lap: ${best_lap.player}, ${fmt(best_lap.best_lap_ms)}` : "";
}

async function main() {
  resize();
  addEventListener("resize", resize);
  placeAtStart();
  requestAnimationFrame(frame);
  try {
    session = await ics.session();
    let saved = "";
    try { saved = localStorage.getItem("race-track.player") || ""; } catch { /* private mode */ }
    $("player").value = saved || session.user.displayName || "";
    if (!session.permissions.includes("race.drive")) {
      $("who").textContent = "You can race, but without the Driver role your result does not go on the board.";
      session = null;
      $("board").hidden = true;
      return;
    }
    $("who").textContent = session.user.displayName ? `Racing as ${session.user.displayName}${judge() ? " (judge)" : ""}` : "Racing as a guest of a link";
    await loadTop();
    setInterval(() => { if (state.phase !== "race") loadTop().catch(() => {}); }, 15000);
  } catch (e) {
    $("who").textContent = `No access to the results (${e.code || e.status}).`;
    $("board").hidden = true;
  }
}

main();
