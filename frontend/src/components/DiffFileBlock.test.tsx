import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { DiffFileChange } from "../api";
import { DiffFileBlock } from "./DiffFileBlock";

// jsdom has no IntersectionObserver, so `observeOnce` calls the callback right
// away and the block behaves as if it were in view.

const file = (over: Partial<DiffFileChange> = {}): DiffFileChange => ({
  path: "index.html",
  change: "modified",
  binary: false,
  added_lines: 4,
  removed_lines: 2,
  size_from: 100,
  size_to: 120,
  ...over,
});

/** A read that never settles, for header-only tests. If it resolved with
 * content, the `setState` after resolve would land outside `act()`. */
const pending = () => new Promise<string>(() => {});

const render1 = (f: DiffFileChange, load: (path: string) => Promise<string> = pending) => {
  const spy = vi.fn(load);
  const utils = render(
    <DiffFileBlock file={f} mode="unified" load={spy} active={false} anchorId="diff-x" />,
  );
  return { ...utils, load: spy };
};

describe("DiffFileBlock", () => {
  it("shows the path and counters in the header", () => {
    render1(file());
    expect(screen.getByText("index.html")).toBeInTheDocument();
    expect(screen.getByText("+4")).toBeInTheDocument();
    expect(screen.getByText("−2")).toBeInTheDocument();
  });

  it("loads the file content once it scrolls into view", async () => {
    const { load } = render1(file(), () => Promise.resolve("@@ -1 +1 @@\n-a\n+b\n"));
    await waitFor(() => expect(load).toHaveBeenCalledWith("index.html"));
    // A diff line renders the sign and the text in separate cells.
    expect(
      await screen.findByText((_, el) => el?.parentElement?.tagName === "CODE" && el.textContent === "+b"),
    ).toBeInTheDocument();
  });

  it("a binary file triggers no request", () => {
    const { load } = render1(
      file({
        path: "logo.png",
        binary: true,
        added_lines: null,
        size_to: 2048,
      }),
    );
    expect(load).not.toHaveBeenCalled();
    expect(screen.getByText(/Binary file/)).toBeInTheDocument();
    expect(screen.getByText(/binary · 2.0 KB/)).toBeInTheDocument();
  });

  it("missing counters (file over the limit) show \"~\" with an explanation", () => {
    render1(file({ added_lines: null, removed_lines: null }));
    expect(screen.getByTitle("File too large: lines not counted")).toBeInTheDocument();
  });

  it("a change with no line differences does not show \"+0 −0\"", () => {
    render1(file({ added_lines: 0, removed_lines: 0 }));
    expect(screen.getByText("no line changes")).toBeInTheDocument();
    expect(screen.queryByText("+0")).not.toBeInTheDocument();
  });

  it("a load error stays inside the block", async () => {
    render1(file(), () => Promise.reject(new Error("500 boom")));
    expect(await screen.findByText(/Server error/)).toBeInTheDocument();
    // The header is still there; the rest of the stack is untouched.
    expect(screen.getByText("index.html")).toBeInTheDocument();
  });

  it("the block has an anchor for jumping from the file tree", () => {
    const { container } = render1(file());
    expect(container.querySelector("#diff-x")).not.toBeNull();
  });

  it("the active block is highlighted", () => {
    const { container } = render(
      <DiffFileBlock file={file()} mode="unified" load={pending} active anchorId="diff-x" />,
    );
    expect(container.querySelector("section")?.className).toContain("border-accent");
  });
});
