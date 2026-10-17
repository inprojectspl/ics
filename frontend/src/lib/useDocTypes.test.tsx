import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { t } from "./i18n";
import { useDocTypeLabel, useDocTypes } from "./useDocTypes";

vi.mock("../api", () => ({
  api: {
    listDocTypes: () =>
      Promise.resolve([
        { key: "design", label: "Design", archived: false },
        { key: "memo", label: "Memo", archived: true },
      ]),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useDocTypeLabel", () => {
  it("names known types, falls back to the key and names untyped documents", async () => {
    const { result } = renderHook(() => useDocTypeLabel(), { wrapper });
    await waitFor(() => expect(result.current("design")).toBe("Design"));
    expect(result.current("custom_type")).toBe("custom_type");
    expect(result.current(null)).toBe(t("assetMetaDialog.noDocType"));
    expect(result.current("")).toBe(t("assetMetaDialog.noDocType"));
  });
});

describe("useDocTypes", () => {
  it("offers only active types while archived ones keep their label", async () => {
    const { result } = renderHook(() => ({ types: useDocTypes(), label: useDocTypeLabel() }), { wrapper });
    await waitFor(() => expect(result.current.types.map((d) => d.key)).toEqual(["design"]));
    expect(result.current.label("memo")).toBe("Memo");
  });
});
