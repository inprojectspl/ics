import { describe, expect, it, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import type { AssetSummary, BindingWithSecret } from "../../api";
import { SecretReveal, SYNC_IMAGE_PLACEHOLDER } from "./SecretReveal";

const authConfig = vi.fn();

vi.mock("../../api", () => ({
  api: { authConfig: (...a: unknown[]) => authConfig(...a) },
}));

const asset = { kind: "md_collection", title: "Docs" } as unknown as AssetSummary;
const secret = {
  id: "b-1",
  public_key: "-----BEGIN PUBLIC KEY-----\nAAA\n-----END PUBLIC KEY-----",
  private_key: "-----BEGIN PRIVATE KEY-----\nBBB\n-----END PRIVATE KEY-----",
} as unknown as BindingWithSecret;

function renderReveal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SecretReveal asset={asset} secret={secret} onDismiss={() => {}} />
    </QueryClientProvider>,
  );
}

describe("SecretReveal sync image", () => {
  beforeEach(() => authConfig.mockReset());

  it("puts the server-configured image into the CI snippet", async () => {
    authConfig.mockResolvedValue({ sync_image: "registry.test/tools/ics-sync:7" });
    renderReveal();
    const hits = await screen.findAllByText(/registry\.test\/tools\/ics-sync:7/);
    expect(hits.length).toBeGreaterThan(0);
    expect(screen.queryByText(new RegExp(SYNC_IMAGE_PLACEHOLDER))).toBeNull();
  });

  it("falls back to a placeholder when the server has no image", async () => {
    authConfig.mockResolvedValue({ sync_image: "" });
    renderReveal();
    const hits = await screen.findAllByText((text) => text.includes(SYNC_IMAGE_PLACEHOLDER));
    expect(hits.length).toBeGreaterThan(0);
  });
});

describe("SecretReveal troubleshooting", () => {
  beforeEach(() => authConfig.mockReset().mockResolvedValue({}));

  it("quotes the messages ics-sync prints for both private key mistakes", () => {
    renderReveal();
    expect(
      screen.getByText("private key: the value after @ is a PEM key, not a file path; pass it without @"),
    ).toBeInTheDocument();
    expect(screen.getByText("private key: cannot read the key file: no such file or directory")).toBeInTheDocument();
    expect(screen.queryByText(/no such file: "\/builds/)).toBeNull();
  });

  it("lets long names and notes wrap instead of overflowing the dialog", () => {
    renderReveal();
    const dt = screen.getByText("403 bad signature");
    expect(dt).toHaveClass("[overflow-wrap:anywhere]");
    expect(dt.closest("dl")).toHaveClass("grid-cols-1", "sm:grid-cols-[fit-content(40%)_minmax(0,1fr)]");
  });
});
