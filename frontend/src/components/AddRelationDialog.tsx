import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type AddRelationBody, type AssetSummary, type RelationType } from "../api";
import { RELATION_TYPES } from "../api/relationTypes";
import { formatApiError } from "../lib/apiError";
import { t, type MessageKey } from "../lib/i18n";
import { qk } from "../lib/queries";
import { relationLabelKey } from "../lib/relationLabels";
import { useDocumentSearch } from "../lib/useDocumentSearch";
import { Button } from "./ui/Button";
import { Field, TEXTAREA_CLASS, inputClass } from "./Field";
import { Dialog } from "./ui/Dialog";

interface Props {
  /** The document the relation starts from; it is never offered as a target. */
  assetId: string;
  slug: string;
  onClose: () => void;
  onAdded: () => void;
}

const HINT: Record<RelationType, MessageKey> = {
  derived_from: "addRelation.hintDerivedFrom",
  supersedes: "addRelation.hintSupersedes",
  depends_on: "addRelation.hintDependsOn",
  part_of: "addRelation.hintPartOf",
  references: "addRelation.hintReferences",
  relates_to: "addRelation.hintRelatesTo",
  duplicates: "addRelation.hintDuplicates",
  contradicts: "addRelation.hintContradicts",
};

// A symmetric relation has no direction, so it cannot point at a heading
// (`relation_anchor_invalid`).
const SYMMETRIC: ReadonlySet<RelationType> = new Set(["relates_to", "contradicts"]);
const NOTE_MAX = 500;
const SEARCH_LIMIT = 20;

const SELECT = inputClass({ size: "lg" });

/** Picks a target document, the relation type and optionally a file and heading. */
export function AddRelationDialog({ assetId, slug, onClose, onAdded }: Props) {
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<AssetSummary | null>(null);
  const [type, setType] = useState<RelationType>("derived_from");
  const [path, setPath] = useState("");
  const [anchor, setAnchor] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const q = query.trim();
  const search = useDocumentSearch(q, SEARCH_LIMIT);
  const results = search.data ?? null;

  const outline = useQuery({
    queryKey: qk.outline(target?.slug ?? ""),
    queryFn: () => api.getOutline(target?.slug ?? ""),
    enabled: target !== null,
  }).data;

  const candidates = (results ?? []).filter(
    (a) => a.id !== assetId && a.slug !== slug,
  );
  const files = target?.kind === "md_collection" ? (outline?.files ?? []) : [];
  const headings = target?.kind === "md_collection"
    ? (files.find((f) => f.path === path)?.headings ?? [])
    : (outline?.headings ?? []);
  const anchorAllowed = !SYMMETRIC.has(type);

  const pick = (a: AssetSummary) => {
    setTarget(a);
    setPath("");
    setAnchor("");
  };

  const submit = async () => {
    if (!target || busy) return;
    const body: AddRelationBody = { relation_type: type, target_id: target.id };
    if (path) body.target_path = path;
    if (anchor && anchorAllowed) body.target_anchor = anchor;
    if (note.trim()) body.note = note.trim();
    setBusy(true);
    setError(null);
    try {
      await api.addRelation(assetId, body);
      onAdded();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog eyebrow={t("relations.addTitle")} title={t("addRelation.title")} onClose={onClose} maxWidth="xl">
      <form
        className="px-6 py-5 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {target ? (
          <div className="flex items-center gap-2 rounded-control border border-accent/40 bg-accent/5 px-3 py-2">
            <span className="flex-1 min-w-0 truncate text-ui text-text-primary">{target.title ?? target.slug}</span>
            <button
              type="button"
              onClick={() => setTarget(null)}
              className="text-meta text-accent hover:underline"
            >
              {t("addRelation.change")}
            </button>
          </div>
        ) : (
          <div>
            <Field label={t("relations.targetLabel")}>
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("addRelation.searchPlaceholder")}
                maxLength={200}
                className={SELECT}
              />
            </Field>
            {candidates.length > 0 && (
              <ul className="mt-2 max-h-56 overflow-y-auto space-y-0.5" aria-label={t("addRelation.results")}>
                {candidates.map((a) => (
                  <li key={a.id}>
                    <button
                      type="button"
                      onClick={() => pick(a)}
                      className="w-full text-left px-2 py-1.5 rounded-control text-ui text-text-primary hover:bg-surface-subtle truncate"
                    >
                      {a.title ?? a.slug}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {results !== null && candidates.length === 0 && (
              <p className="mt-2 text-meta text-text-tertiary">{t("addRelation.noResults")}</p>
            )}
          </div>
        )}

        <Field label={t("relations.typeLabel")} hint={t(HINT[type])}>
          <select value={type} onChange={(e) => setType(e.target.value as RelationType)} className={SELECT}>
            {RELATION_TYPES.map((ty) => (
              <option key={ty} value={ty}>
                {t(relationLabelKey(ty, "out"))}
              </option>
            ))}
          </select>
        </Field>

        {files.length > 0 && (
          <Field label={t("addRelation.file")}>
            <select
              value={path}
              onChange={(e) => {
                setPath(e.target.value);
                setAnchor("");
              }}
              className={SELECT}
            >
              <option value="">{t("addRelation.wholeDocument")}</option>
              {files.map((f) => (
                <option key={f.path} value={f.path}>
                  {f.path}
                </option>
              ))}
            </select>
          </Field>
        )}

        {headings.length > 0 && anchorAllowed && (
          <Field label={t("addRelation.heading")}>
            <select value={anchor} onChange={(e) => setAnchor(e.target.value)} className={SELECT}>
              <option value="">{t("addRelation.noHeading")}</option>
              {headings.map((h) => (
                <option key={h.anchor} value={h.anchor}>
                  {`${"  ".repeat(Math.max(0, h.level - 1))}${h.text}`}
                </option>
              ))}
            </select>
          </Field>
        )}

        <Field label={t("addRelation.note")}>
          <textarea
            value={note}
            maxLength={NOTE_MAX}
            rows={2}
            onChange={(e) => setNote(e.target.value)}
            className={TEXTAREA_CLASS}
          />
        </Field>

        {(error || search.error) && (
          <p role="alert" className="text-ui text-danger">
            {error ?? formatApiError(search.error)}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={!target || busy}>
            {busy ? t("common.saving") : t("relations.add")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
