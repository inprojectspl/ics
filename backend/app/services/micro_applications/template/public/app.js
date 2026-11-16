const notes = ics.collection("notes");
const el = (tag, cls, text) => Object.assign(document.createElement(tag), { className: cls ?? "", textContent: text ?? "" });
async function render() {
  const page = await notes.list({ limit: 50 });
  document.getElementById("count").textContent = String(page.items.length);
  const items = page.items.map((n) => {
    const li = el("li");
    const row = el("div", "row");
    row.append(el("span", "title", n.text));
    if (n.pinned) row.append(el("span", "badge approved", "pinned"));
    const pin = el("button", "", n.pinned ? "Unpin" : "Pin");
    pin.type = "button";
    pin.onclick = async () => { await ics.call("POST", `/v1/custom/notes/${n.id}/toggle-pin`, { body: {}, ifMatch: n.revision }); render(); };
    const actions = el("div", "row actions");
    actions.append(pin);
    li.append(row, actions);
    return li;
  });
  document.getElementById("list").replaceChildren(...(items.length ? items : [el("li", "empty", "No notes yet.")]));
}
document.getElementById("new").onsubmit = async (e) => {
  e.preventDefault();
  await notes.create({ text: e.target.text.value });
  e.target.reset();
  render();
};
render();
