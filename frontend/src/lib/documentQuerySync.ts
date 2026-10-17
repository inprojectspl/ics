import type { QueryClient } from "@tanstack/react-query";
import { onDocumentChange } from "../api/documentChanges";
import { qk } from "./queries";

/** Connect once per application so uploads, dialogs and reader actions agree. */
export function syncDocumentQueries(client: QueryClient): () => void {
  return onDocumentChange(() => {
    void client.invalidateQueries({ queryKey: qk.assets() });
  });
}
