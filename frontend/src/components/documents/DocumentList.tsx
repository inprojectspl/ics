import type { AssetSummary, ProjectSummary } from "../../api";
import type { AssetSortKey } from "../../lib/assetSort";
import { useAssetActions } from "../../lib/useAssetActions";
import { DocumentRow } from "./DocumentRow";

interface Props {
  assets: AssetSummary[];
  projectsById: ReadonlyMap<string, ProjectSummary>;
  /** Refetch after a mutation (rename, delete, pin, a dialog). */
  onChanged: () => void | Promise<void>;
  sortKey?: AssetSortKey;
  hideProject?: boolean;
}

/**
 * The document list of the app: the home list and a project's documents
 * render the same rows with the same actions, on one surface with hairline
 * separators. The parent owns which documents, their order and paging.
 */
export function DocumentList({ assets, projectsById, onChanged, sortKey, hideProject }: Props) {
  const { actions, onCommitRename, onPinChanged, dialogs } = useAssetActions(onChanged);
  if (assets.length === 0) return <>{dialogs}</>;
  return (
    <>
      <div className="overflow-hidden rounded-card border border-border bg-surface shadow-card">
        <ul className="divide-y divide-border">
          {assets.map((a) => (
            <DocumentRow
              key={a.id}
              asset={a}
              projectsById={projectsById}
              onCommitRename={onCommitRename}
              onPinChanged={onPinChanged}
              actions={actions}
              sortKey={sortKey}
              hideProject={hideProject}
            />
          ))}
        </ul>
      </div>
      {dialogs}
    </>
  );
}
