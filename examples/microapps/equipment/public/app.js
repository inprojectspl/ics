// Equipment booking: catalog via CRUD, booking and cancelling via custom
// endpoints that change both tables in one transaction.
const equipment = ics.collection("equipment");
const reservations = ics.collection("reservations");
const $ = (id) => document.getElementById(id);
let statusTimer;
const say = (text) => {
  $("status").textContent = text;
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => { $("status").textContent = ""; }, 4000);
};
const today = () => new Date().toISOString().slice(0, 10);
let names = new Map();

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

const failed = (e) => say(`Error: ${e.code || e.status} ${e.message}`);

function fill(listId, countId, items, empty, render) {
  $(countId).textContent = String(items.length);
  $(listId).replaceChildren(...(items.length ? items.map(render) : [el("li", { class: "empty" }, empty)]));
}

async function loadCatalog(canBook) {
  const page = await equipment.list({ limit: 100, sort: "name" });
  names = new Map(page.items.map((x) => [x.id, x.name]));
  fill("equipment-list", "catalog-count", page.items, "The catalogue is empty.", (x) => {
    const qty = el("input", { type: "number", min: "1", max: "50", value: "1", "aria-label": "Quantity" });
    const book = el("button", { type: "button", class: "primary", onclick: async () => {
      try {
        const r = await ics.call("POST", "/v1/custom/reservations", {
          body: { equipmentId: x.id, startsOn: today(), endsOn: today(), quantity: Number(qty.value) },
        });
        say(`Booked. Available: ${r.available}.`);
        await refresh();
      } catch (e) { failed(e); }
    } }, "Book");
    const stock = el("span", { class: `badge ${x.available ? "approved" : "cancelled"}` }, `${x.available} of ${x.quantity} available`);
    return el("li", { "data-id": x.id },
      el("div", { class: "row" }, el("span", { class: "title" }, x.name), stock),
      el("div", { class: "desc" }, x.category),
      ...(canBook && x.active ? [el("div", { class: "row actions" }, el("span", { class: "qty" }, qty), book)] : []));
  });
}

async function loadMine() {
  const page = await reservations.list({ limit: 100 });
  fill("reservation-list", "mine-count", page.items, "You have no bookings.", (r) => el("li", { "data-id": r.id },
    el("div", { class: "row" },
      el("span", { class: "title" }, names.get(r.equipment_id) ?? r.equipment_id),
      el("span", { class: `badge ${r.status}` }, r.status)),
    el("div", { class: "desc" }, `${r.starts_on} → ${r.ends_on} · ${r.quantity} pcs`),
    ...(r.status === "active" ? [el("div", { class: "row actions" }, el("button", { type: "button", class: "danger", onclick: async () => {
      try {
        const out = await ics.call("POST", `/v1/custom/reservations/${r.id}/cancel`, { body: {}, ifMatch: r.revision });
        say(`Cancelled. Available: ${out.available}.`);
        await refresh();
      } catch (e) { failed(e); }
    } }, "Cancel"))] : [])));
}

let perms = new Set();
async function refresh() {
  if (perms.has("equipment.read")) await loadCatalog(perms.has("reservations.book"));
  if (perms.has("reservations.read")) await loadMine();
}

async function main() {
  const s = await ics.session();
  perms = new Set(s.permissions);
  $("who").textContent = `${s.user.displayName ?? "Guest"} · release ${s.app.release.slice(0, 8)}`;
  $("manage").hidden = !perms.has("equipment.manage");
  $("catalog").hidden = !perms.has("equipment.read");
  $("mine").hidden = !perms.has("reservations.read");
  if (!perms.size) {
    document.querySelector("main").append(el("p", { class: "card empty" }, "You have no permissions in this app yet. Ask its owner to give you a role in ICS."));
  }
  await refresh();
}

$("new-equipment").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const quantity = Number(f.quantity.value);
  try {
    await equipment.create({ name: f.name.value, category: f.category.value, quantity, available: quantity, active: true });
    f.reset();
    say("Equipment added.");
    await refresh();
  } catch (err) { failed(err); }
});

main().catch(failed);
