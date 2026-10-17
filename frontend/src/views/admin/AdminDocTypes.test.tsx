import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { AdminDocType, Me } from "../../api";
import { ApiError } from "../../api/_core";
import { t } from "../../lib/i18n";
import { AdminDocTypes } from "./AdminDocTypes";
import { parseSchema } from "./docTypeDraft";
import { AdminDocTypesLazy } from "./lazy";
import { renderWithClient } from "../../test-utils";

const adminListDocTypes = vi.fn();
const adminCreateDocType = vi.fn();
const adminUpdateDocType = vi.fn();

vi.mock("../../api", () => ({
  api: {
    adminListDocTypes: (...a: unknown[]) => adminListDocTypes(...a),
    adminCreateDocType: (...a: unknown[]) => adminCreateDocType(...a),
    adminUpdateDocType: (...a: unknown[]) => adminUpdateDocType(...a),
  },
}));

const admin = { id: "u", email: "a@example.com", display_name: null, role: "admin" } as Me;

function docType(over: Partial<AdminDocType>): AdminDocType {
  return {
    key: "design",
    label: "Design",
    label_pl: "Projekt",
    label_en: "Design",
    agent_hint: null,
    default_review_days: null,
    properties_schema: {},
    position: 10,
    archived: false,
    archived_at: null,
    ...over,
  };
}

const types = [
  docType({ key: "runbook", label: "Runbook", label_pl: "Runbook", label_en: "Runbook", position: 20, default_review_days: 180 }),
  docType({ key: "offer", label: "Offer", label_pl: "Oferta", label_en: "Offer", position: 30, archived: true, archived_at: "2026-09-01T00:00:00Z" }),
  docType({}),
];

beforeEach(() => {
  adminListDocTypes.mockReset().mockResolvedValue(types);
  adminCreateDocType.mockReset().mockResolvedValue(types[0]);
  adminUpdateDocType.mockReset().mockResolvedValue(types[0]);
});

function openMenu(name: string) {
  fireEvent.click(screen.getByRole("button", { name: t("adminDocTypes.actions", { name }) }));
}

async function list() {
  return within(await screen.findByRole("list", { name: t("adminDocTypes.listLabel") }));
}

describe("AdminDocTypes", () => {
  it("loads lazily behind a Suspense boundary", async () => {
    renderWithClient(
      <Suspense fallback={<p>lazy-fallback</p>}>
        <AdminDocTypesLazy me={admin} />
      </Suspense>,
    );
    expect(screen.getByText("lazy-fallback")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: t("adminDocTypes.title") })).toBeInTheDocument();
    expect(screen.queryByText("lazy-fallback")).not.toBeInTheDocument();
  });

  it("does not fetch for a non-admin", () => {
    renderWithClient(<AdminDocTypes me={{ ...admin, role: "user" }} />);
    expect(adminListDocTypes).not.toHaveBeenCalled();
  });

  it("lists types by position and keeps archived ones, marked", async () => {
    renderWithClient(<AdminDocTypes me={admin} />);
    const rows = (await list()).getAllByRole("listitem");
    expect(rows.map((r) => within(r).getByText(/^(design|runbook|offer)$/).textContent)).toEqual([
      "design",
      "runbook",
      "offer",
    ]);
    const offer = rows[2];
    if (!offer) throw new Error("missing row");
    expect(within(offer).getByText(t("adminDocTypes.archived"))).toBeInTheDocument();
    expect(rows[0] && within(rows[0]).queryByText(t("adminDocTypes.archived"))).toBeNull();
    expect(within(rows[1] as HTMLElement).getByText(/review every 180 days/)).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText(/no review period/)).toBeInTheDocument();
  });

  it("archives a type and restores an archived one through the row menu", async () => {
    renderWithClient(<AdminDocTypes me={admin} />);
    await list();
    openMenu("Design");
    fireEvent.click(screen.getByRole("menuitem", { name: t("adminDocTypes.archive") }));
    await waitFor(() => expect(adminUpdateDocType).toHaveBeenCalledWith("design", { archived: true }));

    openMenu("Offer");
    expect(screen.queryByRole("menuitem", { name: t("adminDocTypes.archive") })).toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: t("adminDocTypes.restore") }));
    await waitFor(() => expect(adminUpdateDocType).toHaveBeenCalledWith("offer", { archived: false }));
  });

  it("creates a type in a dialog and blocks saving invalid JSON with a message", async () => {
    renderWithClient(<AdminDocTypes me={admin} />);
    await list();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("adminDocTypes.createTitle") }));
    const dialog = within(screen.getByRole("dialog", { name: t("adminDocTypes.createTitle") }));
    fireEvent.change(dialog.getByLabelText(t("adminDocTypes.keyLabel")), { target: { value: "policy" } });
    fireEvent.change(dialog.getByLabelText(t("adminDocTypes.labelPl")), { target: { value: "Polityka" } });
    fireEvent.change(dialog.getByLabelText(t("adminDocTypes.labelEn")), { target: { value: "Policy" } });
    // An empty schema stays folded; opening it shows the editor.
    fireEvent.click(dialog.getByRole("button", { name: t("adminDocTypes.schema") }));
    const schema = dialog.getByLabelText(t("adminDocTypes.schemaLabel"));
    fireEvent.change(schema, { target: { value: '{"type": "object",' } });

    expect(dialog.getByRole("alert")).toHaveTextContent(t("adminDocTypes.schemaSyntax"));
    const save = dialog.getByRole("button", { name: t("common.create") });
    expect(save).toBeDisabled();
    fireEvent.submit(save.closest("form") as HTMLFormElement);
    expect(adminCreateDocType).not.toHaveBeenCalled();

    fireEvent.change(schema, { target: { value: '{"type": "object"}' } });
    expect(dialog.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(save);
    await waitFor(() =>
      expect(adminCreateDocType).toHaveBeenCalledWith({
        key: "policy",
        label_pl: "Polityka",
        label_en: "Policy",
        agent_hint: null,
        default_review_days: null,
        properties_schema: { type: "object" },
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the dialog open with the server error when saving fails", async () => {
    adminCreateDocType.mockRejectedValue(new ApiError(409, "exists", "exists", "doc_type_exists"));
    renderWithClient(<AdminDocTypes me={admin} />);
    await list();
    fireEvent.click(screen.getByRole("button", { name: t("adminDocTypes.createTitle") }));
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(dialog.getByLabelText(t("adminDocTypes.keyLabel")), { target: { value: "design" } });
    fireEvent.change(dialog.getByLabelText(t("adminDocTypes.labelPl")), { target: { value: "Projekt" } });
    fireEvent.change(dialog.getByLabelText(t("adminDocTypes.labelEn")), { target: { value: "Design" } });
    fireEvent.click(dialog.getByRole("button", { name: t("common.create") }));
    expect(await dialog.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("edits labels of an existing type from the row title", async () => {
    renderWithClient(<AdminDocTypes me={admin} />);
    await list();
    fireEvent.click(screen.getByRole("button", { name: "Runbook" }));
    const dialog = within(screen.getByRole("dialog", { name: t("adminDocTypes.editTitle", { name: "Runbook" }) }));
    expect(dialog.queryByLabelText(t("adminDocTypes.keyLabel"))).toBeNull();
    expect(dialog.getByLabelText(t("adminDocTypes.reviewDays"))).toHaveValue("180");
    fireEvent.change(dialog.getByLabelText(t("adminDocTypes.labelEn")), { target: { value: "Ops runbook" } });
    fireEvent.click(dialog.getByRole("button", { name: t("common.save") }));
    await waitFor(() =>
      expect(adminUpdateDocType).toHaveBeenCalledWith(
        "runbook",
        expect.objectContaining({ label_en: "Ops runbook", default_review_days: 180, position: 20 }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("opens edit from the row menu and cancels without saving", async () => {
    renderWithClient(<AdminDocTypes me={admin} />);
    await list();
    openMenu("Design");
    fireEvent.click(screen.getByRole("menuitem", { name: t("common.edit") }));
    const dialog = within(screen.getByRole("dialog", { name: t("adminDocTypes.editTitle", { name: "Design" }) }));
    fireEvent.click(dialog.getByRole("button", { name: t("common.cancel") }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(adminUpdateDocType).not.toHaveBeenCalled();
  });
});

describe("parseSchema", () => {
  it("accepts objects and an empty editor, rejects the rest", () => {
    expect(parseSchema("")).toEqual({ ok: true, value: {} });
    expect(parseSchema('{"a": 1}')).toEqual({ ok: true, value: { a: 1 } });
    expect(parseSchema("[1]")).toEqual({ ok: false, reason: "not_object" });
    expect(parseSchema("null")).toEqual({ ok: false, reason: "not_object" });
    expect(parseSchema("{")).toEqual({ ok: false, reason: "syntax" });
  });
});
