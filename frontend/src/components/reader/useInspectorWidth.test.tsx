import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { t } from "../../lib/i18n";
import { InspectorResizeHandle } from "./InspectorResizeHandle";
import { clampInspectorWidth, INSPECTOR_MIN_WIDTH, maxInspectorWidth, useInspectorWidth } from "./useInspectorWidth";

const KEY = "ics-reader-inspector-width";

function Harness() {
  const w = useInspectorWidth();
  return (
    <div>
      <output data-testid="width">{w.width}</output>
      <InspectorResizeHandle {...w} />
    </div>
  );
}

const width = () => Number(screen.getByTestId("width").textContent);
const handle = () => screen.getByRole("separator", { name: t("reader.inspectorResize") });

beforeEach(() => {
  // jsdom has no pointer capture.
  HTMLElement.prototype.setPointerCapture ??= () => {};
  localStorage.removeItem(KEY);
  window.innerWidth = 1600;
});

afterEach(() => localStorage.removeItem(KEY));

describe("inspector width limits", () => {
  it("never goes below the original width nor above half the window", () => {
    expect(clampInspectorWidth(100, 1600)).toBe(INSPECTOR_MIN_WIDTH);
    expect(clampInspectorWidth(900, 1600)).toBe(maxInspectorWidth(1600));
    expect(maxInspectorWidth(1600)).toBeLessThanOrEqual(800);
    // A narrow window still gets the minimum, not less.
    expect(maxInspectorWidth(500)).toBe(INSPECTOR_MIN_WIDTH);
  });
});

describe("InspectorResizeHandle", () => {
  it("widens on a drag to the left and remembers the width only when released", () => {
    render(<Harness />);
    expect(width()).toBe(INSPECTOR_MIN_WIDTH);

    fireEvent.pointerDown(handle(), { button: 0, clientX: 1000, pointerId: 1 });
    fireEvent.pointerMove(handle(), { clientX: 900, pointerId: 1 });
    expect(width()).toBe(INSPECTOR_MIN_WIDTH + 100);
    expect(localStorage.getItem(KEY)).toBeNull();

    fireEvent.pointerUp(handle(), { clientX: 900, pointerId: 1 });
    expect(localStorage.getItem(KEY)).toBe(String(INSPECTOR_MIN_WIDTH + 100));
  });

  it("starts from the remembered width, clamped to the window", () => {
    localStorage.setItem(KEY, "5000");
    render(<Harness />);
    expect(width()).toBe(maxInspectorWidth(1600));
  });

  it("resizes with the keyboard and goes back to the minimum on a double click", () => {
    render(<Harness />);
    fireEvent.keyDown(handle(), { key: "ArrowLeft" });
    expect(width()).toBeGreaterThan(INSPECTOR_MIN_WIDTH);
    expect(handle()).toHaveAttribute("aria-valuenow", String(width()));
    fireEvent.keyDown(handle(), { key: "End" });
    expect(width()).toBe(maxInspectorWidth(1600));

    fireEvent.doubleClick(handle());
    expect(width()).toBe(INSPECTOR_MIN_WIDTH);
    expect(localStorage.getItem(KEY)).toBe(String(INSPECTOR_MIN_WIDTH));
  });
});
