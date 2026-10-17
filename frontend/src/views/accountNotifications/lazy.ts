import { lazy } from "react";

// Visited rarely; App.tsx and the tests use the same lazy component (one
// chunk, see `views/accountScreens.ts`).
export const NotificationSettingsLazy = lazy(() =>
  import("../accountScreens").then((m) => ({ default: m.NotificationSettings })),
);
