import { describe, expect, it } from "vitest";

import { buildPropertiesForm, collectProperties, fromInput, toInput } from "./propertiesForm";

const schema = {
  type: "object",
  required: ["client"],
  properties: {
    client: { type: "string", title: "Client" },
    signed: { type: "string", format: "date" },
    value: { type: "number", description: "Net value in EUR" },
    months: { type: "integer" },
    owners: { type: "array", items: { type: "string" } },
    approved: { type: "boolean" },
    address: { type: "object", properties: { city: { type: "string" } } },
    scores: { type: "array", items: { type: "number" } },
    free: {},
  },
};

describe("buildPropertiesForm", () => {
  const form = buildPropertiesForm(schema);
  const field = (name: string) => form.fields.find((f) => f.name === name);

  it("maps a string to a text field with its title and required flag", () => {
    expect(field("client")).toEqual({ name: "client", label: "Client", kind: "text", required: true });
  });

  it("maps a string with format date to a date field", () => {
    expect(field("signed")).toMatchObject({ kind: "date", label: "signed", required: false });
  });

  it("maps number and integer to number fields", () => {
    expect(field("value")).toMatchObject({ kind: "number", description: "Net value in EUR" });
    expect(field("value")?.integer).toBeUndefined();
    expect(field("months")).toMatchObject({ kind: "number", integer: true });
  });

  it("maps an array of strings to a list field", () => {
    expect(field("owners")).toMatchObject({ kind: "list" });
  });

  it("reports unsupported types instead of guessing", () => {
    expect(form.unsupported).toEqual(["approved", "address", "scores", "free"]);
    expect(form.fields.map((f) => f.name)).toEqual(["client", "signed", "value", "months", "owners"]);
  });

  it("gives an empty form for a schema without properties", () => {
    expect(buildPropertiesForm({})).toEqual({ fields: [], unsupported: [] });
    expect(buildPropertiesForm(null)).toEqual({ fields: [], unsupported: [] });
  });
});

describe("inputs", () => {
  const form = buildPropertiesForm(schema);
  const byName = Object.fromEntries(form.fields.map((f) => [f.name, f]));

  it("round-trips each kind", () => {
    const owners = byName.owners;
    const value = byName.value;
    const months = byName.months;
    if (!owners || !value || !months) throw new Error("fields missing");
    expect(toInput(owners, ["alice", "bob"])).toBe("alice, bob");
    expect(fromInput(owners, " alice, ,bob ")).toEqual({ ok: true, value: ["alice", "bob"] });
    expect(fromInput(value, "12,5")).toEqual({ ok: true, value: 12.5 });
    expect(fromInput(value, "abc")).toEqual({ ok: false });
    expect(fromInput(months, "1.5")).toEqual({ ok: false });
    expect(fromInput(months, "")).toEqual({ ok: true, value: undefined });
  });

  it("keeps unsupported values and reports fields that do not parse", () => {
    const stored = { approved: true, client: "Old", value: 3 };
    expect(collectProperties(form, { client: "ACME", value: "", owners: "a, b" }, stored)).toEqual({
      ok: true,
      value: { approved: true, client: "ACME", owners: ["a", "b"] },
    });
    expect(collectProperties(form, { value: "x" }, stored)).toEqual({ ok: false, invalid: ["value"] });
  });
});
