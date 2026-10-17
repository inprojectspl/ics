import { clsx } from "clsx";

/** Two letters of the project name in a quiet tile: a recognisable anchor
 * without inventing a colour per project. */
export function ProjectMonogram({ name, size = "md" }: { name: string; size?: "md" | "lg" }) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = (words.length > 1 ? `${words[0]?.[0] ?? ""}${words[1]?.[0] ?? ""}` : name.slice(0, 2)).toUpperCase();
  return (
    <span
      aria-hidden
      className={clsx(
        "grid shrink-0 place-items-center rounded-control bg-surface-subtle font-semibold text-text-secondary ring-1 ring-inset ring-border",
        size === "lg" ? "size-12 text-body" : "size-9 text-meta",
      )}
    >
      {letters}
    </span>
  );
}
