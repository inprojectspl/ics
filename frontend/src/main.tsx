import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { syncDocumentQueries } from "./lib/documentQuerySync";
import { LocaleRoot } from "./lib/i18n";
import { installPreloadRecovery } from "./lib/preloadRecovery";
import "./styles/index.css";

// Dev-only import keeps the devtools out of the production bundle, so the
// package can stay a devDependency.
const ReactQueryDevtools = import.meta.env.DEV
  ? lazy(() =>
      import("@tanstack/react-query-devtools").then((m) => ({ default: m.ReactQueryDevtools })),
    )
  : null;

// Defaults tuned for an MCP-driven workload:
// - staleTime 30s: asset metadata changes rarely, and refetch on focus is
//   enough for "back to the tab after lunch" to show fresh data.
// - refetchOnWindowFocus: window focus means the user came back, so refetch.
// - retry: a single attempt, server errors go straight to the toast
//   (FastAPI HTTPException.detail is user-actionable; retries would mask it).
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
});
const stopDocumentSync = syncDocumentQueries(queryClient);
import.meta.hot?.dispose(stopDocumentSync);

installPreloadRecovery(window, window.sessionStorage, () => window.location.reload());

const root = document.getElementById("root");
// index.html always ships the mount node; failing loudly beats rendering nowhere.
if (!root) throw new Error("#root element missing from index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <LocaleRoot>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </LocaleRoot>
      {ReactQueryDevtools && (
        <Suspense fallback={null}>
          <ReactQueryDevtools initialIsOpen={false} />
        </Suspense>
      )}
    </QueryClientProvider>
  </React.StrictMode>,
);
