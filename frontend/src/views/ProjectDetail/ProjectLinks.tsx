import { ExternalLinks } from "./ExternalLinks";
import { KeyDocuments } from "./KeyDocuments";

interface Props {
  slug: string;
  /** Project owner (or admin): edits both sections; everyone else reads. */
  canEdit: boolean;
}

/** Project settings (ADR-0018): the key reading list and the OpenProject mapping. */
export function ProjectLinks({ slug, canEdit }: Props) {
  return (
    <div className="max-w-3xl space-y-4">
      <KeyDocuments slug={slug} canEdit={canEdit} />
      <ExternalLinks slug={slug} canEdit={canEdit} />
    </div>
  );
}
