import { lazy } from "react";

// Visited rarely; App.tsx and the tests use the same lazy component.
export const AccessTokensLazy = lazy(() =>
  import("./accountScreens").then((m) => ({ default: m.AccessTokens })),
);
