import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getMicroAppDocument } from "../../api/microApplications";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { useTheme } from "../../lib/theme";
import { MarkdownView } from "../MarkdownView";
import { Button } from "../ui/Button";

/**
 * The Data tab: the app's records as one Markdown document, rendered like
 * an md asset. Each collection pages on its own; a later page of one
 * collection arrives as its own "(continued)" section and is appended to
 * the document.
 */
export function MicroAppData({ assetId }: { assetId: string }) {
  const theme = useTheme();
  // No refetch on focus: it would replace the first page under rows already appended.
  const doc = useQuery({
    queryKey: ["microapps", assetId, "document"],
    // The page above already shows title, state and permissions.
    queryFn: () => getMicroAppDocument(assetId, { overview: false }),
    refetchOnWindowFocus: false,
  });
  const [appended, setAppended] = useState<{ html: string; markdown: string }>({ html: "", markdown: "" });
  const [cursors, setCursors] = useState<Record<string, string | null>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const column = "max-w-(--reading-width) mx-auto px-(--gutter)";

  if (doc.error)
    return (
      <p role="alert" className={`${column} pt-8 text-ui text-danger`}>
        {formatApiError(doc.error)}
      </p>
    );
  if (!doc.data) return <p className={`${column} pt-8 text-meta text-text-secondary`}>{t("common.loading")}</p>;

  const cursorOf = (name: string, initial: string | null) => (name in cursors ? (cursors[name] ?? null) : initial);

  const loadMore = async (name: string, cursor: string) => {
    setBusy(name);
    setError(null);
    try {
      const page = await getMicroAppDocument(assetId, { collection: name, cursor });
      setAppended((prev) => ({ html: prev.html + (page.html ?? ""), markdown: `${prev.markdown}\n\n${page.markdown}` }));
      setCursors((prev) => ({ ...prev, [name]: page.collections.find((c) => c.name === name)?.next_cursor ?? null }));
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(null);
    }
  };

  const more = doc.data.collections.flatMap((c) => {
    const cursor = c.readable ? cursorOf(c.name, c.next_cursor) : null;
    return cursor ? [{ name: c.name, cursor }] : [];
  });
  return (
    <div className="pb-16">
      {doc.data.html !== undefined ? (
        <MarkdownView html={doc.data.html + appended.html} theme={theme} />
      ) : (
        // An answer without rendered HTML: the text as sent, never parsed here.
        <pre className={`${column} pt-8 whitespace-pre-wrap font-code text-meta text-text-primary`}>
          {doc.data.markdown + appended.markdown}
        </pre>
      )}
      {(more.length > 0 || error) && (
        <div className={`${column} space-y-3`}>
          {error && (
            <p role="alert" className="text-ui text-danger">
              {error}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {more.map(({ name, cursor }) => (
              <Button key={name} size="sm" variant="secondary" busy={busy === name} onClick={() => void loadMore(name, cursor)}>
                {t("microapps.data.more", { name })}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
