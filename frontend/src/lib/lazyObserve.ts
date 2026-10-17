/**
 * Lazy gate for heavy markdown widgets: calls the callback once, when the
 * element first nears the viewport. One module keeps a single idempotency
 * WeakSet for all widgets.
 */

const observed = new WeakSet<Element>();

export function observeOnce(el: Element, cb: () => void): void {
  if (observed.has(el)) return;
  observed.add(el);
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries, obs) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            obs.disconnect();
            cb();
          }
        }
      },
      { rootMargin: "200px 0px" },
    );
    io.observe(el);
  } else {
    cb();
  }
}
