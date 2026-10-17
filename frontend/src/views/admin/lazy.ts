import { lazy } from "react";

// Admin screens load on demand; App.tsx and the tests use the same lazy component.
export const AdminDocTypesLazy = lazy(() =>
  import("./AdminDocTypes").then((m) => ({ default: m.AdminDocTypes })),
);
