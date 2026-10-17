import type { ReactNode } from "react";
import { clsx } from "clsx";

type Width = "content" | "form" | "reading" | "full";

// Width follows the kind of work (DESIGN.md 3): lists and tables use the
// room, settings forms stay a comfortable measure.
const WIDTH: Record<Width, string> = {
  content: "max-w-(--content-width)",
  form: "max-w-3xl",
  reading: "max-w-(--reading-width)",
  full: "",
};

interface Props {
  width?: Width;
  className?: string;
  children: ReactNode;
}

/** Work area of a page: the gutter and the width limit of its kind. */
export function Page({ width = "content", className, children }: Props) {
  return (
    <div className={clsx("mx-auto w-full px-(--gutter) pb-12 pt-6 sm:pt-8", WIDTH[width], className)}>
      {children}
    </div>
  );
}
