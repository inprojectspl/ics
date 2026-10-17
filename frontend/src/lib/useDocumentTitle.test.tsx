import { beforeEach, describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";

import { useDocumentTitle } from "./useDocumentTitle";

beforeEach(() => {
  document.title = "ICS - Internal Content Sharing";
});

describe("useDocumentTitle", () => {
  it("puts the title in the browser tab with the app name after it", () => {
    renderHook(() => useDocumentTitle("Rollout plan"));
    expect(document.title).toBe("Rollout plan - ICS");
  });

  it("follows a title change", () => {
    const { rerender } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: "Plan" as string | null },
    });
    rerender({ title: "Spec" });
    expect(document.title).toBe("Spec - ICS");
  });

  it("restores the previous tab title on unmount", () => {
    const { unmount } = renderHook(() => useDocumentTitle("Plan"));
    unmount();
    expect(document.title).toBe("ICS - Internal Content Sharing");
  });

  it("leaves the tab title alone without a title", () => {
    const { rerender } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: "Plan" as string | null },
    });
    rerender({ title: null });
    expect(document.title).toBe("ICS - Internal Content Sharing");
  });
});
