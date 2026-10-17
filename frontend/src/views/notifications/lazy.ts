import { lazy } from "react";

// App.tsx and the tests use the same lazy components (one chunk, see
// `views/accountScreens.ts`).
export const NotificationsViewLazy = lazy(() =>
  import("../accountScreens").then((m) => ({ default: m.NotificationsView })),
);

export const NotificationsUnsubscribeLazy = lazy(() =>
  import("../accountScreens").then((m) => ({ default: m.NotificationsUnsubscribe })),
);
