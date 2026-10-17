import { lazy } from "react";

// Opened from the project page; App.tsx and the tests use the same lazy component.
export const ProjectDocumentMapLazy = lazy(() =>
  import("./ProjectDocumentMap").then((m) => ({ default: m.ProjectDocumentMap })),
);
