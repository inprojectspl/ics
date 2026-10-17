import { lazy } from "react";

// Opened from the sidebar and the reader; App.tsx and the tests use the same lazy component.
export const GraphExplorerLazy = lazy(() =>
  import("./GraphExplorer").then((m) => ({ default: m.GraphExplorer })),
);
