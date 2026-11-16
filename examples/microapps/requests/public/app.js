// Rejestr wniosków: own requests through generic CRUD, approval through the
// custom endpoint. All data access goes through window.ics (same origin).
const requests = ics.collection("requests");
const $ = (id) => document.getElementById(id);
const say = (text) => { $("status").textContent = text; };

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

function failed(err) {
  say(`Błąd: ${err.code || err.status} ${err.message}`);
}

async function loadMine() {
  const page = await requests.list({ limit: 50 });
  $("my-list").replaceChildren(...page.items.map((r) => {
    const actions = el("div", { class: "row" });
    if (r.status === "submitted") {
      actions.append(
        el("button", { onclick: async () => {
          const title = prompt("Nowy tytuł", r.title);
          if (!title) return;
          try { await requests.update(r.id, r.revision, { title }); say("Zapisano."); await loadMine(); } catch (e) { failed(e); }
        } }, "Edytuj"),
        el("button", { onclick: async () => {
          try { await requests.remove(r.id, r.revision); say("Usunięto."); await loadMine(); } catch (e) { failed(e); }
        } }, "Usuń"),
      );
    }
    return el("li", { "data-id": r.id },
      el("div", { class: "row" }, el("strong", {}, r.title), el("span", { class: `badge ${r.status}` }, r.status)),
      r.description ? el("div", {}, r.description) : "",
      actions);
  }));
}

async function loadReview() {
  const page = await ics.call("GET", "/v1/custom/review-requests", { query: { limit: 50 } });
  $("review-list").replaceChildren(...page.items.map((r) =>
    el("li", { "data-id": r.id },
      el("strong", {}, r.title),
      r.description ? el("div", {}, r.description) : "",
      el("div", { class: "row" }, el("button", { onclick: async () => {
        try {
          await ics.call("POST", `/v1/custom/requests/${r.id}/approve`, { body: {}, ifMatch: r.revision });
          say("Zatwierdzono.");
          await loadReview();
        } catch (e) { failed(e); }
      } }, "Zatwierdź")))));
}

async function main() {
  const s = await ics.session();
  $("who").textContent = `${s.user.displayName ?? "Gość"} · wydanie ${s.app.release.slice(0, 8)}`;
  const can = new Set(s.permissions);
  if (can.has("requests.read") || can.has("requests.create")) {
    $("mine").hidden = false;
    await loadMine();
  }
  if (can.has("requests.approve")) {
    $("review").hidden = false;
    await loadReview();
  }
  if (!can.size) say("Nie masz jeszcze uprawnień w tej aplikacji. Poproś opiekuna o przydział w ICS.");
}

$("new-request").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  try {
    await requests.create({ title: form.title.value, description: form.description.value });
    form.reset();
    say("Złożono wniosek.");
    await loadMine();
  } catch (err) { failed(err); }
});

main().catch(failed);
