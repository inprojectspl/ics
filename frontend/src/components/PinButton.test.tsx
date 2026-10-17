import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PinButton } from "./PinButton";

vi.mock("../api", () => ({
  api: {
    pinAsset: vi.fn().mockResolvedValue(undefined),
    unpinAsset: vi.fn().mockResolvedValue(undefined),
  },
}));

// Imported after the mock so the functions are mocks, not the real api.
const { api } = await import("../api");

describe("PinButton", () => {
  beforeEach(() => {
    vi.mocked(api.pinAsset).mockClear();
    vi.mocked(api.unpinAsset).mockClear();
  });

  it("renders a button with aria-pressed=false when unpinned", () => {
    render(<PinButton assetId="a-1" pinned={false} onToggled={() => {}} />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false");
  });

  it("renders aria-pressed=true when pinned", () => {
    render(<PinButton assetId="a-1" pinned={true} onToggled={() => {}} />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  });

  it("clicking when unpinned calls api.pinAsset and onToggled(true)", async () => {
    const onToggled = vi.fn();
    render(<PinButton assetId="abc" pinned={false} onToggled={onToggled} />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(api.pinAsset).toHaveBeenCalledWith("abc"));
    expect(onToggled).toHaveBeenCalledWith(true);
  });

  it("clicking when pinned calls api.unpinAsset and onToggled(false)", async () => {
    const onToggled = vi.fn();
    render(<PinButton assetId="xyz" pinned={true} onToggled={onToggled} />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(api.unpinAsset).toHaveBeenCalledWith("xyz"));
    expect(onToggled).toHaveBeenCalledWith(false);
  });

  it("stops event propagation (the asset card click does not fire)", () => {
    const onToggled = vi.fn();
    const onCardClick = vi.fn();
    render(
      <div onClick={onCardClick}>
        <PinButton assetId="x" pinned={false} onToggled={onToggled} />
      </div>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onCardClick).not.toHaveBeenCalled();
  });
});
