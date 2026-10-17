import { lazy } from "react";

// A debugging screen; App.tsx and the tests use the same lazy component.
export const TaskAgentViewLazy = lazy(() =>
  import("../TaskAgentView").then((m) => ({ default: m.TaskAgentView })),
);
