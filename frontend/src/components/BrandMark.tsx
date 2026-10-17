import { clsx } from "clsx";

interface Props {
  /** Width/height in pixels. Square. */
  size?: number;
  /** Show the "ICS" wordmark next to the icon. */
  withWord?: boolean;
  /** Optional extra class on the wrapper (margin, link, etc.). */
  className?: string;
  /** Hide the wordmark below `sm`, where the chrome needs the room. */
  compactWord?: boolean;
}

/**
 * Logo + optional wordmark. Small sizes use the simplified favicon;
 * larger sizes use the full network mark. The text inherits the UI font
 * and theme, while standalone brand lockups use vector lettering.
 */
export function BrandMark({ size = 22, withWord = true, className, compactWord = false }: Props) {
  return (
    <span className={clsx("inline-flex items-center gap-2 min-w-0", className)}>
      <img
        src={size < 32 ? "/favicon.svg" : "/logo.svg"}
        width={size}
        height={size}
        alt=""
        aria-hidden="true"
        // `display:block` removes the inline baseline gap under the SVG.
        className="block shrink-0 select-none"
        draggable={false}
      />
      {withWord && (
        <span
          className={clsx(
            "font-semibold tracking-[0.04em] text-current leading-none",
            compactWord && "hidden sm:inline",
          )}
        >
          ICS
        </span>
      )}
    </span>
  );
}
