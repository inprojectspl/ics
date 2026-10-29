import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Me } from "./api";
import { ConfirmProvider } from "./components/ConfirmDialog";
import { AppShell } from "./components/shell/AppShell";
import { ToastProvider } from "./components/Toast";
import { NotificationStreamRoot } from "./components/notifications/NotificationStreamRoot";
import type { AgentFormat } from "./lib/agentView";
import { t } from "./lib/i18n";
import { sessionQuery } from "./lib/useSessionUser";
import { Home } from "./views/Home";
import { Viewer } from "./views/Viewer";
import { ShareView } from "./views/ShareView";
// Lazy, declared next to the view so its test exercises the same boundary.
import { AdminDocTypesLazy as AdminDocTypes } from "./views/admin/lazy";
import { AccessTokensLazy as AccessTokens } from "./views/accessTokensLazy";
import { GraphExplorerLazy as GraphExplorer } from "./views/GraphExplorer/lazy";
import { ProjectDocumentMapLazy as ProjectDocumentMap } from "./views/ProjectDocumentMap/lazy";
import { ProjectHygieneLazy as ProjectHygiene } from "./views/hygiene/lazy";
import { TaskAgentViewLazy as TaskAgentView } from "./views/taskAgent/lazy";
import {
  NotificationsUnsubscribeLazy as NotificationsUnsubscribe,
  NotificationsViewLazy as NotificationsView,
} from "./views/notifications/lazy";
import { NotificationSettingsLazy as NotificationSettings } from "./views/accountNotifications/lazy";
import { safeNextPath } from "./lib/nextPath";

// Common entry points (Home for signed-in users, Viewer/ShareView from
// bookmarks and email links) stay eager. The rest is lazy: admin views see
// about 0-2% of daily traffic, setup/reset are one-shot, and projects opens
// once per session. This saves about 60-70KB in the initial chunk.
const Login = lazy(() => import("./views/Login").then((m) => ({ default: m.Login })));
const Setup = lazy(() => import("./views/Setup").then((m) => ({ default: m.Setup })));
const ResetRequest = lazy(() =>
  import("./views/ResetRequest").then((m) => ({ default: m.ResetRequest })),
);
const ResetConfirm = lazy(() =>
  import("./views/ResetConfirm").then((m) => ({ default: m.ResetConfirm })),
);
const AdminAudit = lazy(() =>
  import("./views/AdminAudit").then((m) => ({ default: m.AdminAudit })),
);
const AdminCdn = lazy(() => import("./views/AdminCdn").then((m) => ({ default: m.AdminCdn })));
const AdminReview = lazy(() =>
  import("./views/AdminReview").then((m) => ({ default: m.AdminReview })),
);
const AdminUsers = lazy(() =>
  import("./views/AdminUsers").then((m) => ({ default: m.AdminUsers })),
);
const Projects = lazy(() => import("./views/Projects").then((m) => ({ default: m.Projects })));
const ProjectDetail = lazy(() =>
  import("./views/ProjectDetail").then((m) => ({ default: m.ProjectDetail })),
);
const AcceptInvite = lazy(() =>
  import("./views/AcceptInvite").then((m) => ({ default: m.AcceptInvite })),
);
const AgentView = lazy(() =>
  import("./views/AgentView").then((m) => ({ default: m.AgentView })),
);
const VersionDiff = lazy(() =>
  import("./views/VersionDiff").then((m) => ({ default: m.VersionDiff })),
);

type Route =
  | { name: "home" }
  | { name: "viewer"; slug: string; path?: string; version?: number; tab?: "relations" }
  | { name: "version-diff"; slug: string; from?: number; to?: number }
  | { name: "agent-view"; slug: string; path?: string; format?: AgentFormat; version?: number }
  | { name: "share"; token: string; path?: string; version?: number }
  | { name: "admin-audit" }
  | { name: "admin-review" }
  | { name: "admin-cdn" }
  | { name: "admin-doc-types" }
  | { name: "admin-users" }
  | { name: "access-tokens" }
  | { name: "account-notifications" }
  | { name: "notifications" }
  | { name: "notifications-unsubscribe"; token: string }
  | { name: "graph"; doc?: string }
  | { name: "projects" }
  | { name: "project"; slug: string }
  | { name: "project-map"; slug: string }
  | { name: "project-hygiene"; slug: string }
  | { name: "project-agent"; slug: string }
  | { name: "project-accept"; slug: string; token: string }
  | { name: "login"; next?: string }
  | { name: "setup"; token: string; next?: string }
  | { name: "reset-request" }
  | { name: "reset-confirm"; token: string };

/** `?ver=N` is a read-only preview of an archived version. Garbage
 * ("abc", "0", "-3") counts as no parameter: the backend would reject it
 * anyway, and the current version is a safer fallback than an error. */
function parsePositiveInt(raw: string | null): number | undefined {
  if (!raw) return undefined;
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 ? n : undefined;
}

function parseVersionParam(params: URLSearchParams): number | undefined {
  return parsePositiveInt(params.get("ver"));
}

/** `#login?next=/v/<slug>`: where to return after login. Only same-origin
 * paths are accepted so the resolver cannot become an open redirect. The URL
 * parser decides, not a prefix check: `//evil.example` is easy to spot, but
 * `/\evil.example` is not, and the browser normalizes the backslash to a
 * slash and leaves the origin. */
function parseNext(hash: string): string | undefined {
  const q = hash.indexOf("?");
  if (q === -1) return undefined;
  return safeNextPath(new URLSearchParams(hash.slice(q + 1)).get("next"));
}

function parseRoute(): Route {
  const hash = window.location.hash.replace(/^#/, "");
  const params = new URLSearchParams(window.location.search);
  const path = window.location.pathname;

  // Must run before the viewer route: the viewer regex ends at the slug, so
  // `/v/<slug>/diff` (and `/agent`) would not match at all, and a looser pattern would
  // swallow `diff` into the slug.
  const diff = path.match(/^\/v\/([a-z0-9]+)\/diff\/?$/i);
  if (diff?.[1])
    return {
      name: "version-diff",
      slug: diff[1],
      from: parsePositiveInt(params.get("from")),
      to: parsePositiveInt(params.get("to")),
    };
  const agent = path.match(/^\/v\/([a-z0-9]+)\/agent\/?$/i);
  if (agent?.[1]) {
    const fmt = params.get("fmt");
    return {
      name: "agent-view",
      slug: agent[1],
      path: params.get("p") || undefined,
      format: fmt === "raw" || fmt === "markdown" ? fmt : undefined,
      version: parseVersionParam(params),
    };
  }
  const viewer = path.match(/^\/v\/([a-z0-9]+)\/?$/i);
  if (viewer?.[1])
    return {
      name: "viewer",
      slug: viewer[1],
      path: params.get("p") || undefined,
      version: parseVersionParam(params),
      tab: params.get("tab") === "relations" ? "relations" : undefined,
    };
  const share = path.match(/^\/s\/([A-Za-z0-9_-]+)\/?$/);
  if (share?.[1])
    return {
      name: "share",
      token: share[1],
      // Guests navigate a collection with hash fragments, but `?p=` must work
      // on entry: owners copy `/s/<token>?p=file.md` from the address bar and
      // pass it on.
      path: params.get("p") || undefined,
      version: parseVersionParam(params),
    };
  const projectAccept = path.match(/^\/projects\/([a-z0-9]+)\/accept\/?$/i);
  if (projectAccept?.[1])
    return {
      name: "project-accept",
      slug: projectAccept[1],
      token: params.get("t") ?? "",
    };
  const projectMap = path.match(/^\/projects\/([a-z0-9]+)\/map\/?$/i);
  if (projectMap?.[1]) return { name: "project-map", slug: projectMap[1] };
  const projectHygiene = path.match(/^\/projects\/([a-z0-9]+)\/hygiene\/?$/i);
  if (projectHygiene?.[1]) return { name: "project-hygiene", slug: projectHygiene[1] };
  const projectAgent = path.match(/^\/projects\/([a-z0-9]+)\/agent\/?$/i);
  if (projectAgent?.[1]) return { name: "project-agent", slug: projectAgent[1] };
  const project = path.match(/^\/projects\/([a-z0-9]+)\/?$/i);
  if (project?.[1]) return { name: "project", slug: project[1] };
  if (path === "/projects" || path === "/projects/") return { name: "projects" };
  if (path === "/graph" || path === "/graph/") return { name: "graph", doc: params.get("doc") || undefined };
  if (path === "/shared" || path === "/shared/") {
    // Legacy route: redirect to the consolidated Home with the
    // shared-with-me filter applied. One list, one filter taxonomy.
    window.history.replaceState({}, "", "/?f=state%3Ashared-with-me");
    return { name: "home" };
  }
  if (path === "/admin/audit") return { name: "admin-audit" };
  if (path === "/admin/review") return { name: "admin-review" };
  if (path === "/admin/cdn") return { name: "admin-cdn" };
  if (path === "/admin/doc-types") return { name: "admin-doc-types" };
  if (path === "/admin/users") return { name: "admin-users" };
  if (path === "/account/tokens") return { name: "access-tokens" };
  if (path === "/account/notifications") return { name: "account-notifications" };
  if (path === "/notifications" || path === "/notifications/") return { name: "notifications" };
  if (path === "/notifications/unsubscribe")
    return { name: "notifications-unsubscribe", token: params.get("token") ?? "" };
  if (path === "/setup")
    return { name: "setup", token: params.get("token") ?? "", next: safeNextPath(params.get("next")) };
  if (path === "/reset-confirm")
    return { name: "reset-confirm", token: params.get("token") ?? "" };
  // Exact match despite `?next=`: a bare `startsWith` would route any hash
  // starting with these letters (`#loginfoo`) to login.
  if (hash === "login" || hash.startsWith("login?"))
    return { name: "login", next: parseNext(hash) };
  if (hash === "reset-request") return { name: "reset-request" };
  return { name: "home" };
}

function LoadingFallback() {
  return (
    <div role="status" className="flex min-h-[50dvh] flex-1 items-center justify-center text-ui text-text-secondary">
      {t("app.loading")}
    </div>
  );
}

export function App() {
  return (
    <ToastProvider>
      <ConfirmProvider>
        <NotificationStreamRoot />
        <Suspense fallback={<LoadingFallback />}>
          <Router />
        </Suspense>
      </ConfirmProvider>
    </ToastProvider>
  );
}

function Router() {
  const [route, setRoute] = useState<Route>(parseRoute());

  useEffect(() => {
    const onChange = () => setRoute(parseRoute());
    window.addEventListener("hashchange", onChange);
    window.addEventListener("popstate", onChange);
    return () => {
      window.removeEventListener("hashchange", onChange);
      window.removeEventListener("popstate", onChange);
    };
  }, []);

  // viewer & share open without requiring an auth-state probe (which would
  // 401 noisily for external users); they resolve auth themselves. The
  // session user lives in the query cache only (`qk.me()`), where the reader
  // and `NotificationStreamRoot` read it too.
  const needsSession =
    route.name !== "viewer" && route.name !== "share" && route.name !== "notifications-unsubscribe";
  const session = useQuery({ ...sessionQuery, enabled: needsSession });
  const me: Me | null | "unknown" = session.data ?? (session.isError ? null : "unknown");
  const { refetch } = session;

  const onLogged = useCallback(async () => {
    await refetch();
  }, [refetch]);

  // Public-by-default routes. The reader resolves the session itself (link
  // visitors land there too) and fills the query cache, so the shell turns
  // into the signed-in one as soon as the answer arrives, around the same
  // mounted reader.
  if (route.name === "viewer")
    return (
      <AppShell me={session.data ?? null}>
        <Suspense fallback={<LoadingFallback />}>
          <Viewer slug={route.slug} path={route.path} version={route.version} tab={route.tab} />
        </Suspense>
      </AppShell>
    );
  if (route.name === "share")
    return (
      <AppShell me={null}>
        <Suspense fallback={<LoadingFallback />}>
          <ShareView token={route.token} path={route.path} version={route.version} />
        </Suspense>
      </AppShell>
    );
  if (route.name === "project-accept")
    return <AcceptInvite token={route.token} />;
  if (route.name === "setup")
    return (
      <Setup
        token={route.token}
        onDone={() => {
          const next = route.next;
          window.history.pushState({}, "", next ? `/#login?next=${encodeURIComponent(next)}` : "/#login");
          setRoute({ name: "login", next });
        }}
      />
    );
  if (route.name === "reset-confirm")
    return (
      <ResetConfirm
        token={route.token}
        onDone={() => {
          window.history.pushState({}, "", "/#login");
          setRoute({ name: "login" });
        }}
      />
    );
  if (route.name === "reset-request") return <ResetRequest />;
  // The e-mail footer link works without a session (RFC 8058 opt-out).
  if (route.name === "notifications-unsubscribe")
    return <NotificationsUnsubscribe token={route.token} />;

  if (me === "unknown") return <LoadingFallback />;
  if (me === null) return <Login onLogged={onLogged} next={route.name === "login" ? route.next : undefined} />;
  // Every signed-in page renders inside the same shell element, so React
  // keeps it (and the sidebar state) mounted across route changes; a lazy
  // page suspends inside it, never above it.
  return (
    <AppShell me={me}>
      <Suspense fallback={<LoadingFallback />}>
        <SignedInPage route={route} me={me} />
      </Suspense>
    </AppShell>
  );
}

function SignedInPage({ route, me }: { route: Route; me: Me }) {
  switch (route.name) {
    case "admin-audit":
      return <AdminAudit me={me} />;
    case "admin-review":
      return <AdminReview me={me} />;
    case "admin-cdn":
      return <AdminCdn me={me} />;
    case "admin-doc-types":
      return <AdminDocTypes me={me} />;
    case "admin-users":
      return <AdminUsers me={me} />;
    case "access-tokens":
      return <AccessTokens me={me} />;
    case "account-notifications":
      return <NotificationSettings me={me} />;
    case "notifications":
      return <NotificationsView />;
    case "version-diff":
      return <VersionDiff slug={route.slug} from={route.from} to={route.to} />;
    case "agent-view":
      return (
        <AgentView
          slug={route.slug}
          path={route.path}
          format={route.format}
          version={route.version}
        />
      );
    case "graph":
      return <GraphExplorer doc={route.doc} />;
    case "projects":
      return <Projects />;
    case "project":
      return <ProjectDetail me={me} slug={route.slug} />;
    case "project-map":
      return <ProjectDocumentMap me={me} slug={route.slug} />;
    case "project-hygiene":
      return <ProjectHygiene me={me} slug={route.slug} />;
    case "project-agent":
      return <TaskAgentView me={me} slug={route.slug} />;
    default:
      return <Home me={me} />;
  }
}
