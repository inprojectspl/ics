/**
 * "Repoint to successor": task links of a superseded document move to the
 * document that replaced it, so the tasks stop pointing at outdated content.
 */
import { api, type RelationNode } from "../../api";
import { ApiError } from "../../api/_core";

/** The visible document that supersedes `slug`, if any. */
export async function findSuccessor(slug: string): Promise<RelationNode | null> {
  const rel = await api.listRelations(slug, { types: ["supersedes"], direction: "in" });
  return rel.incoming.superseded_by?.[0]?.other ?? null;
}

/** Moves every external link from one document to another; returns how many moved. */
export async function moveExternalRefs(fromId: string, toId: string): Promise<number> {
  const refs = await api.listExternalRefs(fromId);
  let moved = 0;
  for (const ref of refs) {
    try {
      await api.addExternalRef(toId, {
        system: ref.system,
        entity: ref.entity,
        external_id: ref.external_id,
        external_scope: ref.external_scope,
        role: ref.role,
        required: ref.required,
        label: ref.label,
        url: ref.url,
        note: ref.note,
      });
    } catch (e) {
      // The successor already has this link: dropping the old one is enough.
      if (!(e instanceof ApiError && e.code === "external_ref_exists")) throw e;
    }
    await api.deleteExternalRef(ref.id);
    moved += 1;
  }
  return moved;
}
