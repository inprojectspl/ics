// The browser tab title as two parts: the page title (`useDocumentTitle`)
// and a prefix (the unread count, "(3) "). Both are stored here and the tab
// shows prefix + page title, so neither writer has to parse the other's
// text back out of `document.title`.

let base: string | null = null;
let prefix = "";

function render(): void {
  document.title = prefix + (base ?? "");
}

/** The page title, without the prefix. Before anyone set it, the title
 * the document loaded with (index.html). */
export function pageTitle(): string {
  return base ?? document.title;
}

export function setPageTitle(title: string): void {
  base = title;
  render();
}

export function setTitlePrefix(next: string): void {
  base = pageTitle();
  prefix = next;
  render();
}
