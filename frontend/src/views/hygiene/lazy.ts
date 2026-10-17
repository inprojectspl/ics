import { lazy } from "react";

// A maintenance screen for owners and editors; App.tsx and the tests use the same lazy component.
export const ProjectHygieneLazy = lazy(() =>
  import("../ProjectHygiene").then((m) => ({ default: m.ProjectHygiene })),
);
