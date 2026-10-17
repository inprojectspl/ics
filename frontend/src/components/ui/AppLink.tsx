import { forwardRef, type AnchorHTMLAttributes, type MouseEvent } from "react";
import { isPlainClick, navigate } from "../../lib/navigate";

interface Props extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string;
}

/**
 * In-app link: a plain click changes the route without a page load, while
 * modifier and middle clicks keep the browser's own behaviour (new tab).
 * External, download and targeted links are left alone.
 */
export const AppLink = forwardRef<HTMLAnchorElement, Props>(function AppLink(
  { href, onClick, target, download, ...rest },
  ref,
) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || target || download !== undefined || !isPlainClick(e)) return;
    if (!href.startsWith("/") || href.startsWith("//") || href.startsWith("/api/")) return;
    e.preventDefault();
    navigate(href);
  };
  return <a ref={ref} href={href} target={target} download={download} onClick={handle} {...rest} />;
});
