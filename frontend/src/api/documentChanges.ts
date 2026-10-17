/** Successful writes affecting document discovery, independent of the view. */
const listeners = new Set<() => void>();

export function onDocumentChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function notifyDocumentChange(path: string, method = "GET") {
  if (["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) return;
  if (!/^\/api\/(assets|projects|bindings|shares|relations)(?:\/|\?|$)/.test(path)) return;
  for (const listener of listeners) listener();
}
