// Allocates until the guest heap limit is hit.
export default async function alloc() {
  const keep = [];
  for (;;) keep.push(new Array(1e6).fill(1));
}
