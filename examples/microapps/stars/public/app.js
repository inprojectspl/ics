// Star Hunt: players of one room share a channel (`arena/<room>`). Positions
// go out about 15 times a second; one page, the host (the member with the
// lowest id), owns the stars and the scores of the round and tells the others.
// Messages are best effort, so the host repeats its state every two seconds
// and a page that joins late catches up from it.
const W = 800, H = 500, SPEED = 240, R = 14, STAR = 12, STARS = 6, ROUND_MS = 60000, PAUSE_MS = 5000;
const $ = (id) => document.getElementById(id);
const canvas = $("arena"), g = canvas.getContext("2d");
const scores = ics.collection("scores");

let me = null;             // {id, name}
let room = null;           // channel object
let roomName = "";
let members = [];          // presence, sorted by id
const players = new Map(); // id -> {x, y, name, at}
let stars = [];            // [{id, x, y}]
let points = {};           // id -> stars this round
let endsAt = 0;            // local clock
let pausedUntil = 0;
let lastSent = 0;
let lastState = 0;
const keys = new Set();

const isHost = () => members.length > 0 && members[0].id === me.id;
const color = (id) => `hsl(${[...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7)} 70% 50%)`;
const rand = (min, max) => min + Math.random() * (max - min);
const newStar = () => ({ id: Math.random().toString(36).slice(2, 10), x: rand(30, W - 30), y: rand(30, H - 30) });

function el(tag, text, attrs = {}) {
  const n = document.createElement(tag);
  n.textContent = text;
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

// ------------------------------------------------------------ the host

function startRound() {
  stars = Array.from({ length: STARS }, newStar);
  points = {};
  endsAt = performance.now() + ROUND_MS;
  pausedUntil = 0;
  sendState();
}

function sendState() {
  lastState = performance.now();
  room?.send({ k: "state", stars, points, left: Math.max(0, endsAt - performance.now()), pause: Math.max(0, pausedUntil - performance.now()) });
}

function take(starId, playerId) {
  const i = stars.findIndex((s) => s.id === starId);
  if (i < 0 || performance.now() > endsAt) return;
  stars.splice(i, 1, newStar());
  points[playerId] = (points[playerId] ?? 0) + 1;
  sendState();
}

function endRound() {
  pausedUntil = performance.now() + PAUSE_MS;
  room?.send({ k: "end", points });
  finished(points);
  sendState();
}

// ------------------------------------------------------------ every page

async function finished(final) {
  const mine = final[me.id] ?? 0;
  $("banner").textContent = mine ? `Round over: you caught ${mine}.` : "Round over.";
  if (mine > 0) {
    try {
      await scores.create({ player: me.name.slice(0, 60), room: roomName, stars: mine });
    } catch (e) {
      $("banner").textContent += ` (score not saved: ${e.code ?? e.status})`;
    }
  }
}

function onMessage(d, from) {
  if (!d || typeof d !== "object") return;
  if (d.k === "pos" && Number.isFinite(d.x) && Number.isFinite(d.y)) {
    players.set(from.id, { x: d.x, y: d.y, name: from.name, at: performance.now() });
  } else if (d.k === "state" && Array.isArray(d.stars) && from.id === members[0]?.id) {
    stars = d.stars.slice(0, 20);
    points = d.points ?? {};
    endsAt = performance.now() + Number(d.left || 0);
    pausedUntil = performance.now() + Number(d.pause || 0);
  } else if (d.k === "take" && isHost()) {
    take(String(d.id), from.id);
  } else if (d.k === "end" && from.id === members[0]?.id) {
    finished(d.points ?? {});
  }
}

function join(name) {
  room?.leave();
  roomName = name;
  players.clear();
  stars = [];
  points = {};
  endsAt = 0;
  location.hash = name;
  room = ics.realtime.channel(`arena/${name}`);
  room.on("message", onMessage);
  room.on("presence", (list) => {
    members = [...list].sort((a, b) => (a.id < b.id ? -1 : 1));
    for (const id of players.keys()) if (!members.some((m) => m.id === id)) players.delete(id);
    // A new member gets the round at once; a new host carries it on.
    if (isHost()) (endsAt || pausedUntil ? sendState : startRound)();
    drawPlayers();
  });
  canvas.focus();
}

function drawPlayers() {
  $("players").replaceChildren(...members.map((m) => {
    const li = el("li", `${m.name}${m.id === me.id ? " (you)" : ""}${m.id === members[0]?.id ? " · host" : ""}`);
    li.style.color = color(m.id);
    li.append(el("b", ` ${points[m.id] ?? 0}`));
    return li;
  }));
}

async function loadBoard() {
  const page = await scores.list({ limit: 10, sort: "-stars" });
  $("board").replaceChildren(...page.items.map((s) => el("li", `${s.player}: ${s.stars} (${s.room})`)));
}

// ------------------------------------------------------------ the loop

const self = { x: rand(50, W - 50), y: rand(50, H - 50) };
let last = performance.now();

function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  const dx = (keys.has("ArrowRight") || keys.has("d")) - (keys.has("ArrowLeft") || keys.has("a"));
  const dy = (keys.has("ArrowDown") || keys.has("s")) - (keys.has("ArrowUp") || keys.has("w"));
  const moved = dx || dy;
  if (moved) {
    const len = Math.hypot(dx, dy);
    self.x = Math.max(R, Math.min(W - R, self.x + (dx / len) * SPEED * dt));
    self.y = Math.max(R, Math.min(H - R, self.y + (dy / len) * SPEED * dt));
  }
  if (room && now - lastSent > (moved ? 66 : 1000)) {
    lastSent = now;
    room.send({ k: "pos", x: Math.round(self.x), y: Math.round(self.y) });
  }
  const playing = endsAt > now && pausedUntil < now;
  if (playing) {
    for (const s of stars) {
      if (s.taken || Math.hypot(s.x - self.x, s.y - self.y) > R + STAR) continue;
      s.taken = true; // hidden until the host answers
      if (isHost()) take(s.id, me.id);
      else room.send({ k: "take", id: s.id });
    }
  }
  if (isHost()) {
    if (endsAt && now > endsAt && !pausedUntil) endRound();
    else if (pausedUntil && now > pausedUntil) startRound();
    else if (now - lastState > 2000) sendState();
  }
  draw(now, playing);
  requestAnimationFrame(frame);
}

function draw(now, playing) {
  g.clearRect(0, 0, W, H);
  g.fillStyle = "#0f1724";
  g.fillRect(0, 0, W, H);
  for (const s of stars) {
    if (s.taken) continue;
    g.fillStyle = "#ffd34d";
    g.beginPath();
    for (let i = 0; i < 10; i++) {
      const r = i % 2 ? STAR / 2.2 : STAR, a = (Math.PI / 5) * i - Math.PI / 2;
      g.lineTo(s.x + r * Math.cos(a), s.y + r * Math.sin(a));
    }
    g.fill();
  }
  const dot = (x, y, id, name) => {
    g.fillStyle = color(id);
    g.beginPath();
    g.arc(x, y, R, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = "#e8eef7";
    g.font = "12px system-ui";
    g.textAlign = "center";
    g.fillText(name, x, y - R - 6);
  };
  for (const [id, p] of players) if (now - p.at < 5000) dot(p.x, p.y, id, p.name);
  if (me) dot(self.x, self.y, me.id, "you");
  g.fillStyle = "#e8eef7";
  g.font = "bold 16px system-ui";
  g.textAlign = "left";
  const left = Math.max(0, Math.ceil((endsAt - now) / 1000));
  g.fillText(playing ? `${left} s` : pausedUntil > now ? "Next round soon" : "Waiting for the host", 12, 24);
  if (Math.floor(now / 500) % 2 === 0) drawPlayers();
}

// ------------------------------------------------------------ start

addEventListener("keydown", (e) => {
  if (e.target instanceof HTMLInputElement) return;
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "w", "a", "s", "d"].includes(k)) {
    keys.add(k);
    e.preventDefault();
  }
});
addEventListener("keyup", (e) => keys.delete(e.key.length === 1 ? e.key.toLowerCase() : e.key));
addEventListener("blur", () => keys.clear());

$("room-form").addEventListener("submit", (e) => {
  e.preventDefault();
  join($("room").value.trim());
});

ics.realtime.on("status", (s) => {
  $("status").textContent = s === "open" ? "live" : s;
  $("status").className = `status ${s}`;
});

(async () => {
  const s = await ics.session();
  me = { id: s.user.id, name: s.user.displayName || "Player" };
  if (!s.permissions.includes("stars.play")) {
    $("banner").textContent = "You have no role in this app yet; ask its owner.";
    return;
  }
  scores.watch(() => loadBoard().catch(() => {}));
  const start = decodeURIComponent(location.hash.slice(1)).match(/^[A-Za-z0-9_-]{1,64}$/)?.[0] ?? "lobby";
  $("room").value = start;
  join(start);
  requestAnimationFrame(frame);
})().catch((e) => { $("banner").textContent = `Error: ${e.code ?? e.status ?? e.message}`; });
