import { useEffect } from "react";
import { t } from "./i18n";
import { pageTitle, setPageTitle } from "./documentTitle";

/**
 * Show `title` in the browser tab, so several open documents can be told
 * apart. Without a title the tab keeps whatever it had (the app name from
 * `index.html`); unmount puts the previous title back.
 */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (!title) return;
    // Through `documentTitle`, so the unread "(3) " prefix stays.
    const previous = pageTitle();
    setPageTitle(t("app.documentTitle", { title }));
    return () => {
      setPageTitle(previous);
    };
  }, [title]);
}
