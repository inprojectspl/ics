/**
 * Stand-ins for the heavy readers and dialogs in `Viewer.test.tsx`: each one
 * exposes the props the view computes and the callbacks it wires.
 */

export const MarkdownView = (p: { html: string; title: string; downloadHref?: string }) => (
  <article data-testid="md" data-title={p.title} data-download={p.downloadHref ?? ""}>
    <div dangerouslySetInnerHTML={{ __html: p.html }} />
  </article>
);

export const HtmlBundleView = (p: { title: string; fetchGrantUrl: () => Promise<string> }) => (
  <button
    type="button"
    onClick={async () => document.body.setAttribute("data-grant", await p.fetchGrantUrl())}
  >
    bundle {p.title}
  </button>
);

// The PDF reader draws canvases through pdf.js.
export const PdfDocument = (p: { url: string; downloadHref?: string; accessGated?: boolean }) => (
  <div
    data-testid="pdf"
    data-url={p.url}
    data-download={p.downloadHref ?? ""}
    data-gated={String(!!p.accessGated)}
  />
);

export const InlineEditor = (p: { path?: string; onCancel: () => void; onSaved: () => Promise<void> }) => (
  <div data-testid="editor" data-path={p.path ?? ""}>
    <button type="button" onClick={p.onCancel}>
      cancel
    </button>
    <button type="button" onClick={() => void p.onSaved()}>
      save
    </button>
  </div>
);

export const NewFileDialog = (p: { defaultFolder: string; onClose: () => void }) => (
  <div role="dialog" data-folder={p.defaultFolder}>
    <button type="button" onClick={p.onClose}>
      close
    </button>
  </div>
);

export const VaultGraph = (p: { fetcher: () => Promise<unknown>; onOpenFile: (p: string) => void }) => (
  <div data-testid="graph">
    <button type="button" onClick={() => void p.fetcher()}>
      fetch graph
    </button>
    <button type="button" onClick={() => p.onOpenFile("b.md")}>
      open b.md
    </button>
  </div>
);

export const CollectionFiles = (p: {
  tree: string[];
  onSelect: (path: string) => void;
  onCreateFile?: () => void;
  onUploadFile?: () => void;
}) => (
  <div data-testid="files">
    {p.tree.map((path) => (
      <button key={path} type="button" onClick={() => p.onSelect(path)}>
        tree {path}
      </button>
    ))}
    {p.onCreateFile && (
      <button type="button" onClick={p.onCreateFile}>
        new file
      </button>
    )}
    {p.onUploadFile && (
      <button type="button" onClick={p.onUploadFile}>
        upload file
      </button>
    )}
  </div>
);
