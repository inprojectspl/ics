import { useRef } from "react";

import { t } from "../../lib/i18n";
import type { InspectorWidth } from "./useInspectorWidth";

/** Keyboard step of the separator, in px. */
const STEP = 24;

/**
 * Vertical separator on the inspector's left edge: dragging it (or the
 * arrow keys while it has focus) changes the inspector width; a double
 * click goes back to the narrowest width. The panel sits on the right,
 * so moving left widens it.
 */
export function InspectorResizeHandle({ width, min, max, setWidth }: InspectorWidth) {
  const drag = useRef<{ x: number; width: number; last: number } | null>(null);

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t("reader.inspectorResize")}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width}
      tabIndex={0}
      title={t("reader.inspectorResizeHint")}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        drag.current = { x: e.clientX, width, last: width };
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!d) return;
        d.last = d.width + (d.x - e.clientX);
        setWidth(d.last);
      }}
      onPointerUp={() => {
        const d = drag.current;
        drag.current = null;
        if (d) setWidth(d.last, true);
      }}
      onPointerCancel={() => {
        drag.current = null;
      }}
      onDoubleClick={() => setWidth(min, true)}
      onKeyDown={(e) => {
        const next =
          e.key === "ArrowLeft" ? width + STEP
          : e.key === "ArrowRight" ? width - STEP
          : e.key === "Home" ? min
          : e.key === "End" ? max
          : null;
        if (next === null) return;
        e.preventDefault();
        setWidth(next, true);
      }}
      className="group absolute inset-y-0 -left-1.5 z-20 w-3 cursor-col-resize touch-none outline-none"
    >
      <span
        aria-hidden
        className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-transparent transition-colors duration-150 group-hover:bg-accent group-focus-visible:bg-accent group-active:bg-accent"
      />
    </div>
  );
}
