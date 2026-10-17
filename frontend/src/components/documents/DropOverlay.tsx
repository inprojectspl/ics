import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { UploadCloud } from "lucide-react";
import { t } from "../../lib/i18n";
import { useEnterMotion } from "../../lib/motion";

interface Props {
  /** Where the files go, e.g. "Documents" or a project name. */
  target: string;
  /** Who will see them (the stored upload mode, in words). */
  audience: string;
  onDrop: (dt: DataTransfer) => void;
  disabled?: boolean;
}

function carriesFiles(e: DragEvent): boolean {
  return Boolean(e.dataTransfer?.types.includes("Files"));
}

/**
 * Files dragged over the page show one quiet drop target over the work
 * area, gone again on leave. Dragging text or a link is left alone, and
 * nothing in the layout moves.
 */
export function DropOverlay({ target, audience, onDrop, disabled = false }: Props) {
  const [active, setActive] = useState(false);
  const depth = useRef(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const onDropRef = useRef(onDrop);
  useEffect(() => {
    onDropRef.current = onDrop;
  });
  useEnterMotion(panelRef, "fade", active);

  useEffect(() => {
    if (disabled) return;
    const enter = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setActive(true);
    };
    const over = (e: DragEvent) => {
      if (carriesFiles(e)) e.preventDefault();
    };
    const leave = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    };
    const drop = (e: DragEvent) => {
      if (!carriesFiles(e) || !e.dataTransfer) return;
      // A drop inside a dialog's own drop area is handled there.
      if ((e.target as Element | null)?.closest?.("[role=dialog]")) {
        depth.current = 0;
        setActive(false);
        return;
      }
      e.preventDefault();
      depth.current = 0;
      setActive(false);
      onDropRef.current(e.dataTransfer);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [disabled]);

  if (!active) return null;
  return createPortal(
    <div className="pointer-events-none fixed inset-0 z-40 p-3 sm:p-6" aria-hidden>
      <div
        ref={panelRef}
        className="flex h-full w-full flex-col items-center justify-center gap-2 rounded-overlay border-2 border-dashed border-accent bg-accent-soft/90 text-center"
      >
        <UploadCloud size={32} strokeWidth={1.5} className="text-accent" />
        <p className="text-title font-semibold text-text-primary">{t("upload.dropTo", { target })}</p>
        <p className="text-ui text-text-secondary">{audience}</p>
      </div>
    </div>,
    document.body,
  );
}
