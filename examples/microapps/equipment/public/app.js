// Rezerwacje sprzętu: catalog via CRUD, booking and cancelling via custom
// endpoints that change both tables in one transaction.
const equipment = ics.collection("equipment");
const reservations = ics.collection("reservations");
const $ = (id) => document.getElementById(id);
const say = (text) => { $("status").textContent = text; };
const today = () => new Date().toISOString().slice(0, 10);
let names = new Map();

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

const failed = (e) => say(`Błąd: ${e.code || e.status} ${e.message}`);

async function loadCatalog(canBook) {
  const page = await equipment.list({ limit: 100, sort: "name" });
  names = new Map(page.items.map((x) => [x.id, x.name]));
  $("equipment-list").replaceChildren(...page.items.map((x) => {
    const qty = el("input", { type: "number", min: "1", max: "50", value: "1", "aria-label": "Liczba" });
    const book = el("button", { onclick: async () => {
      try {
        const r = await ics.call("POST", "/v1/custom/reservations", {
          body: { equipmentId: x.id, startsOn: today(), endsOn: today(), quantity: Number(qty.value) },
        });
        say(`Zarezerwowano. Dostępne: ${r.available}.`);
        await refresh();
      } catch (e) { failed(e); }
    } }, "Rezerwuj");
    return el("li", { "data-id": x.id },
      el("strong", {}, x.name), el("span", {}, `${x.category} · dostępne ${x.available}/${x.quantity}`),
      ...(canBook && x.active ? [qty, book] : []));
  }));
}

async function loadMine() {
  const page = await reservations.list({ limit: 100 });
  $("reservation-list").replaceChildren(...page.items.map((r) => el("li", { "data-id": r.id },
    el("strong", {}, names.get(r.equipment_id) ?? r.equipment_id),
    el("span", {}, `${r.starts_on} → ${r.ends_on} · ${r.quantity} szt. · ${r.status}`),
    ...(r.status === "active" ? [el("button", { onclick: async () => {
      try {
        const out = await ics.call("POST", `/v1/custom/reservations/${r.id}/cancel`, { body: {}, ifMatch: r.revision });
        say(`Anulowano. Dostępne: ${out.available}.`);
        await refresh();
      } catch (e) { failed(e); }
    } }, "Anuluj")] : []))));
}

let perms = new Set();
async function refresh() {
  if (perms.has("equipment.read")) await loadCatalog(perms.has("reservations.book"));
  if (perms.has("reservations.read")) await loadMine();
}

async function main() {
  const s = await ics.session();
  perms = new Set(s.permissions);
  $("who").textContent = `${s.user.displayName ?? "Gość"} · wydanie ${s.app.release.slice(0, 8)}`;
  $("manage").hidden = !perms.has("equipment.manage");
  $("catalog").hidden = !perms.has("equipment.read");
  $("mine").hidden = !perms.has("reservations.read");
  if (!perms.size) say("Nie masz jeszcze uprawnień w tej aplikacji.");
  await refresh();
}

$("new-equipment").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const quantity = Number(f.quantity.value);
  try {
    await equipment.create({ name: f.name.value, category: f.category.value, quantity, available: quantity, active: true });
    f.reset();
    say("Dodano sprzęt.");
    await refresh();
  } catch (err) { failed(err); }
});

main().catch(failed);
