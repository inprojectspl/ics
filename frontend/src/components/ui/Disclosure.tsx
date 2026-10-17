import { useId, useRef, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { ChevronRight } from "lucide-react";
import { useEnterMotion } from "../../lib/motion";

interface Props {
  title: ReactNode;
  /** Right side of the header row (a count, an action). */
  aside?: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  children: ReactNode;
}

/** A section that can be folded: the chevron and `aria-expanded` say so. */
export function Disclosure({ title, aside, defaultOpen = false, className, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const [touched, setTouched] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const id = useId();
  // Animate only a change the user made, not the first render.
  useEnterMotion(bodyRef, "reveal", open && touched);
  return (
    <section className={className}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => {
            setTouched(true);
            setOpen((v) => !v);
          }}
          className="-ml-1.5 flex min-w-0 flex-1 items-center gap-1.5 rounded-control px-1.5 py-1.5 text-left text-body font-semibold text-text-primary hover:bg-surface-hover"
        >
          <ChevronRight
            size={16}
            aria-hidden
            className={clsx("shrink-0 text-text-secondary transition-transform duration-150 ease-standard", open && "rotate-90")}
          />
          <span className="min-w-0 truncate">{title}</span>
        </button>
        {aside}
      </div>
      <div ref={bodyRef} id={id} hidden={!open} className="pt-2">
        {children}
      </div>
    </section>
  );
}
