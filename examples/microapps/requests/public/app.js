// Request register: own requests through generic CRUD, approval through the
// custom endpoint. All data access goes through window.ics (same origin).
const requests = ics.collection("requests");
const $ = (id) => document.getElementById(id);
const STATUS = { submitted: "submitted", approved: "approved" };

let statusTimer;
const say = (text) => {
  $("status").textContent = text;
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => { $("status").textContent = ""; }, 4000);
};

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
  say(`Error: ${err.code || err.status} ${err.message}`);
}

function fill(listId, countId, items, empty, render) {
  $(countId).textContent = String(items.length);
  $(listId).replaceChildren(...(items.length ? items.map(render) : [el("li", { class: "empty" }, empty)]));
}

const heading = (r) =>
  el("div", { class: "row" },
    el("span", { class: "title" }, r.title),
    el("span", { class: `badge ${r.status}` }, STATUS[r.status] ?? r.status));

async function loadMine() {
  const page = await requests.list({ limit: 50 });
  fill("my-list", "mine-count", page.items, "You have no requests yet.", (r) => {
    const actions = el("div", { class: "row actions" });
    if (r.status === "submitted") {
      actions.append(
        el("button", { type: "button", onclick: async () => {
          const title = prompt("New title", r.title);
          if (!title) return;
          try { await requests.update(r.id, r.revision, { title }); say("Saved."); await loadMine(); } catch (e) { failed(e); }
        } }, "Edit"),
        el("button", { type: "button", class: "danger", onclick: async () => {
          try { await requests.remove(r.id, r.revision); say("Deleted."); await loadMine(); } catch (e) { failed(e); }
        } }, "Delete"),
      );
    }
    return el("li", { "data-id": r.id }, heading(r), r.description ? el("div", { class: "desc" }, r.description) : "", actions);
  });
}

async function loadReview() {
  const page = await ics.call("GET", "/v1/custom/review-requests", { query: { limit: 50 } });
  fill("review-list", "review-count", page.items, "Nothing is waiting for approval.", (r) =>
    el("li", { "data-id": r.id },
      heading(r),
      r.description ? el("div", { class: "desc" }, r.description) : "",
      el("div", { class: "row actions" }, el("button", { type: "button", class: "primary", onclick: async () => {
        try {
          await ics.call("POST", `/v1/custom/requests/${r.id}/approve`, { body: {}, ifMatch: r.revision });
          say("Approved.");
          await loadReview();
        } catch (e) { failed(e); }
      } }, "Approve"))));
}

async function main() {
  const s = await ics.session();
  $("who").textContent = `${s.user.displayName ?? "Guest"} · release ${s.app.release.slice(0, 8)}`;
  const can = new Set(s.permissions);
  if (can.has("requests.read") || can.has("requests.create")) {
    $("mine").hidden = false;
    await loadMine();
  }
  if (can.has("requests.approve")) {
    $("review").hidden = false;
    await loadReview();
  }
  if (!can.size) {
    document.querySelector("main").append(el("p", { class: "card empty" }, "You have no permissions in this app yet. Ask its owner to give you a role in ICS."));
  }
}

$("new-request").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  try {
    await requests.create({ title: form.title.value, description: form.description.value });
    form.reset();
    say("Request submitted.");
    await loadMine();
  } catch (err) { failed(err); }
});

main().catch(failed);
