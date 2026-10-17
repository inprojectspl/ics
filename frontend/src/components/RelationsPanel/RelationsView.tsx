import { t } from "../../lib/i18n";
import { RelationsPanel } from "./RelationsPanel";

interface Props {
  slug: string;
  assetId: string;
  title: string;
  canEdit: boolean;
  /** Address of the document itself, for the way back. */
  documentHref: string;
}

/** The reader's `?tab=relations`: every relation with the editing actions. */
export function RelationsView({ slug, assetId, title, canEdit, documentHref }: Props) {
  return (
    <article className="max-w-(--reading-width) mx-auto px-(--gutter) py-10">
      <p className="text-meta text-text-secondary mb-1 font-medium">
        {t("relations.tabTitle")}
      </p>
      <h1 className="text-h2 text-text-primary mb-2 break-words">{title}</h1>
      <a href={documentHref} className="text-ui text-accent hover:underline">
        {t("relations.backToDocument")}
      </a>
      <div className="mt-6">
        <RelationsPanel slug={slug} assetId={assetId} canEdit={canEdit} />
      </div>
    </article>
  );
}
