import { memo, useCallback, useMemo, useState } from "react";
import { clsx } from "clsx";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Pencil, Plus, Tags } from "lucide-react";

import { api, type AdminDocType, type DocTypeCreate, type DocTypeUpdate, type Me } from "../../api";
import { AdminPage } from "../../components/AdminPage";
import { EmptyState } from "../../components/EmptyState";
import { LoadingListSkeleton } from "../../components/LoadingListSkeleton";
import { docTypeColor } from "../../components/graph";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { DATA_ROW, DataList } from "../../components/ui/DataList";
import { Dialog } from "../../components/ui/Dialog";
import { Menu } from "../../components/ui/Menu";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatApiError } from "../../lib/apiError";
import { t, tn } from "../../lib/i18n";
import { qk } from "../../lib/queries";
import { DocTypeForm } from "./DocTypeForm";

interface Props {
  me: Me;
}

/** What the dialog is doing: nothing, a new type, or editing one by key. */
type Editor = null | { mode: "create" } | { mode: "edit"; key: string };

function byPosition(a: AdminDocType, b: AdminDocType): number {
  return a.position - b.position || a.key.localeCompare(b.key);
}

/**
 * Doc type vocabulary (ADR-0015): labels in both languages, agent hint,
 * review period and the JSON Schema of `properties`. A type is never deleted;
 * an archived one stays listed so existing documents keep their label.
 * Creating and editing happen in one dialog, opened from the header or a row.
 */
export function AdminDocTypes({ me }: Props) {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: qk.adminDocTypes(),
    queryFn: api.adminListDocTypes,
    enabled: me.role === "admin",
  });
  const [editor, setEditor] = useState<Editor>(null);
  const [busy, setBusy] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const sorted = useMemo(() => (list.data ? [...list.data].sort(byPosition) : null), [list.data]);
  const edited = editor?.mode === "edit" ? (sorted?.find((d) => d.key === editor.key) ?? null) : null;
  const error = listError ?? (list.error ? formatApiError(list.error) : null);

  const run = useCallback(async (call: () => Promise<unknown>, onError: (msg: string) => void): Promise<boolean> => {
    setBusy(true);
    try {
      await call();
      // The public list feeds the badges and pickers, so it follows the admin list.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.adminDocTypes() }),
        queryClient.invalidateQueries({ queryKey: qk.docTypes() }),
      ]);
      return true;
    } catch (e) {
      onError(formatApiError(e));
      return false;
    } finally {
      setBusy(false);
    }
  }, [queryClient]);

  const open = (next: Editor) => {
    setFormError(null);
    setEditor(next);
  };
  const save = async (call: () => Promise<unknown>) => {
    setFormError(null);
    if (await run(call, setFormError)) setEditor(null);
  };
  // Stable across renders, so the memoised rows only redraw when their type changes.
  const editType = useCallback((key: string) => {
    setFormError(null);
    setEditor({ mode: "edit", key });
  }, []);
  const setArchived = useCallback(
    (key: string, archived: boolean) => {
      setListError(null);
      void run(() => api.adminUpdateDocType(key, { archived }), setListError);
    },
    [run],
  );

  return (
    <AdminPage me={me} tab="doc-types">
      <PageHeader
        title={t("adminDocTypes.title")}
        description={t("adminDocTypes.intro")}
        actions={
          <Button icon={<Plus size={16} aria-hidden />} onClick={() => open({ mode: "create" })}>
            {t("adminDocTypes.createTitle")}
          </Button>
        }
      />

      {error && (
        <p role="alert" className="mb-4 text-ui text-danger">
          {error}
        </p>
      )}

      {sorted === null ? (
        list.isPending && <LoadingListSkeleton rows={6} />
      ) : sorted.length === 0 ? (
        <EmptyState icon={Tags} title={t("adminDocTypes.emptyTitle")} description={t("adminDocTypes.empty")} />
      ) : (
        <DataList label={t("adminDocTypes.listLabel")}>
          {sorted.map((d) => (
            <DocTypeRow
              key={d.key}
              docType={d}
              busy={busy}
              onEdit={editType}
              onArchive={setArchived}
            />
          ))}
        </DataList>
      )}

      {editor && (editor.mode === "create" || edited) && (
        <Dialog
          title={edited ? t("adminDocTypes.editTitle", { name: edited.label }) : t("adminDocTypes.createTitle")}
          onClose={() => setEditor(null)}
          maxWidth="2xl"
        >
          {edited ? (
            <DocTypeForm
              mode="edit"
              docType={edited}
              busy={busy}
              error={formError}
              onUpdate={(key: string, body: DocTypeUpdate) => void save(() => api.adminUpdateDocType(key, body))}
              onCancel={() => setEditor(null)}
            />
          ) : (
            <DocTypeForm
              mode="create"
              busy={busy}
              error={formError}
              onCreate={(body: DocTypeCreate) => void save(() => api.adminCreateDocType(body))}
              onCancel={() => setEditor(null)}
            />
          )}
        </Dialog>
      )}
    </AdminPage>
  );
}

const DocTypeRow = memo(function DocTypeRow({
  docType: d,
  busy,
  onEdit,
  onArchive,
}: {
  docType: AdminDocType;
  busy: boolean;
  onEdit: (key: string) => void;
  onArchive: (key: string, archived: boolean) => void;
}) {
  const label = t("adminDocTypes.actions", { name: d.label });
  return (
    <li className={DATA_ROW}>
      <span aria-hidden className="mt-2 size-2.5 shrink-0 self-start rounded-full" style={{ backgroundColor: docTypeColor(d.key) }} />
      <div className={clsx("min-w-0 flex-1", d.archived && "opacity-60")}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <button
            type="button"
            onClick={() => onEdit(d.key)}
            className="text-left text-item font-medium text-text-primary after:absolute after:inset-0 hover:text-accent"
          >
            {d.label}
          </button>
          <code className="font-code text-meta text-text-secondary">{d.key}</code>
          {d.archived && <Badge>{t("adminDocTypes.archived")}</Badge>}
        </div>
        <p className="mt-0.5 text-meta text-text-secondary">
          {d.label_pl} / {d.label_en}
          {" · "}
          {d.default_review_days == null
            ? t("adminDocTypes.noReview")
            : tn("adminDocTypes.reviewEvery", d.default_review_days)}
        </p>
        {d.agent_hint && <p className="mt-0.5 line-clamp-2 text-meta text-text-tertiary">{d.agent_hint}</p>}
      </div>
      <div className="relative z-10 shrink-0">
        <Menu
          label={label}
          actions={[
            { key: "edit", label: t("common.edit"), icon: Pencil, onClick: () => onEdit(d.key), disabled: busy },
            d.archived
              ? { key: "restore", label: t("adminDocTypes.restore"), icon: ArchiveRestore, onClick: () => onArchive(d.key, false), disabled: busy }
              : { key: "archive", label: t("adminDocTypes.archive"), icon: Archive, onClick: () => onArchive(d.key, true), disabled: busy, danger: true },
          ]}
        />
      </div>
    </li>
  );
});
