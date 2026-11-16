const notes = ics.collection("notes");
async function render() {
  const page = await notes.list({ limit: 50 });
  const list = document.getElementById("list");
  list.replaceChildren(...page.items.map((n) => {
    const li = document.createElement("li");
    li.textContent = (n.pinned ? "📌 " : "") + n.text;
    const pin = document.createElement("button");
    pin.textContent = "Pin";
    pin.onclick = async () => { await ics.call("POST", `/v1/custom/notes/${n.id}/toggle-pin`, { body: {}, ifMatch: n.revision }); render(); };
    li.append(pin);
    return li;
  }));
}
document.getElementById("new").onsubmit = async (e) => {
  e.preventDefault();
  await notes.create({ text: e.target.text.value });
  e.target.reset();
  render();
};
render();
