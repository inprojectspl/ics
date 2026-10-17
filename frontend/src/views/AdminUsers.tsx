import { memo, useCallback, useEffect, useState } from "react";
import { clsx } from "clsx";
import { ChevronDown, ChevronRight, Lock, Shield, UserPlus, Users } from "lucide-react";
import { AdminUser, Me, api } from "../api";
import { AdminPage } from "../components/AdminPage";
import { EmptyState } from "../components/EmptyState";
import { InviteUserDialog } from "../components/InviteUserDialog";
import { LoadingListSkeleton } from "../components/LoadingListSkeleton";
import { Pagination } from "../components/Pagination";
import { SearchInput } from "../components/SearchInput";
import { UserDetailDialog } from "../components/UserDetailDialog";
import { Badge } from "../components/ui/Badge";
import { Button, buttonClass } from "../components/ui/Button";
import { ChipTabs } from "../components/ui/ChipTabs";
import { DATA_ROW, DataList } from "../components/ui/DataList";
import { Menu } from "../components/ui/Menu";
import { PageHeader } from "../components/ui/PageHeader";
import { PageToolbar } from "../components/ui/PageToolbar";
import { formatApiError } from "../lib/apiError";
import { formatBytes, formatRelative } from "../lib/format";
import { t, tn, type MessageKey } from "../lib/i18n";
import { initials } from "../lib/initials";
import { AUTH_METHOD_LABEL, USER_ROLE_LABEL } from "../lib/roles";
import { replaceUrl } from "../lib/navigate";
import { useDebouncedValue } from "../lib/useDebouncedValue";
import { useLocation } from "../lib/useLocation";
import { useResettablePage } from "../lib/useResettablePage";

interface Props {
  me: Me;
}

type StatusFilter = "" | "locked" | "unverified" | "active30d" | "password" | "google_sso";
type RoleFilter = "" | "user" | "admin" | "external";

export function AdminUsers({ me }: Props) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.adminUsersList>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<RoleFilter>("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);
  // `?user=<id>` opens that person's card: the audit log links here.
  const linkedId = useLocation().search.get("user");

  const PAGE_SIZE = 25;

  // The search box fires a request per change, so the value it feeds is
  // debounced; the input itself stays fully controlled.
  const debouncedSearch = useDebouncedValue(search);
  const [page, setPage] = useResettablePage(
    JSON.stringify([debouncedSearch, role, statusFilter]),
  );

  const refresh = useCallback(
    () =>
      api
        .adminUsersList({
          q: debouncedSearch.trim() || undefined,
          role: role || undefined,
          status: statusFilter || undefined,
          page,
          page_size: PAGE_SIZE,
        })
        .then(setData, (e) => setError(formatApiError(e))),
    [debouncedSearch, role, statusFilter, page],
  );

  useEffect(() => {
    if (me.role !== "admin") return;
    void refresh();
  }, [me.role, refresh]);

  useEffect(() => {
    if (me.role !== "admin" || !linkedId) return;
    api.adminUserGet(linkedId).then(setSelectedUser, (e) => setError(formatApiError(e)));
  }, [me.role, linkedId]);

  const closeUser = () => {
    setSelectedUser(null);
    if (linkedId) replaceUrl("/admin/users");
  };

  const summary = data?.summary;
  const roleLabel = t(ROLES.find((r) => r.key === role)?.label ?? "adminUsers.anyRole");
  return (
    <AdminPage me={me} tab="users">
      <PageHeader
        title={t("adminUsers.title")}
        description={summary ? t("adminUsers.summaryLine", { total: summary.total, admins: summary.admins }) : t("adminUsers.intro")}
        actions={
          <Button icon={<UserPlus size={16} aria-hidden />} onClick={() => setInviteOpen(true)}>
            {t("adminUsers.invite")}
          </Button>
        }
      />

      {summary && (
        <ChipTabs
          label={t("adminUsers.statusFilter")}
          active={statusFilter}
          onChange={setStatusFilter}
          items={[
            { key: "", label: t("adminUsers.chipAll"), count: summary.total },
            { key: "active30d", label: t("adminUsers.chipActive30d"), count: summary.active_30d },
            { key: "unverified", label: t("adminUsers.chipUnverified"), count: summary.unverified },
            { key: "locked", label: t("adminUsers.chipLocked"), count: summary.locked },
          ]}
        />
      )}

      <PageToolbar
        className="mt-4"
        start={
          <>
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder={t("adminUsers.searchPlaceholder")}
              ariaLabel={t("adminUsers.searchPlaceholder")}
              className="min-w-0 basis-full sm:basis-auto sm:w-64 lg:w-72 xl:w-96"
            />
            <Menu
              label={t("adminUsers.roleFilter")}
              align="start"
              actions={ROLES.map((r) => ({ key: r.key || "any", label: t(r.label), checked: r.key === role, onClick: () => setRole(r.key) }))}
              trigger={(props) => (
                <button type="button" {...props} aria-label={`${t("adminUsers.roleFilter")}: ${roleLabel}`} className={buttonClass("secondary")}>
                  <Shield size={16} aria-hidden className="text-text-secondary" />
                  {roleLabel}
                  <ChevronDown size={14} aria-hidden className="text-text-secondary" />
                </button>
              )}
            />
          </>
        }
      />

      <div className="mt-4">
        {error ? (
          <EmptyState icon={Users} title={t("adminUsers.loadFailed")} description={error} />
        ) : data === null ? (
          <LoadingListSkeleton rows={6} />
        ) : data.users.length === 0 ? (
          <EmptyState icon={Users} title={t("adminUsers.empty")} />
        ) : (
          <DataList label={t("adminUsers.title")}>
            {data.users.map((u) => (
              <UserRow key={u.id} user={u} onPick={setSelectedUser} />
            ))}
          </DataList>
        )}
        {data && <Pagination page={data.page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />}
      </div>

      {inviteOpen && (
        <InviteUserDialog
          onClose={() => setInviteOpen(false)}
          onCreated={async () => {
            setInviteOpen(false);
            await refresh();
          }}
        />
      )}
      {selectedUser && (
        <UserDetailDialog
          user={selectedUser}
          onClose={closeUser}
          onChanged={async () => {
            await refresh();
            // Re-pick the up-to-date row so the dialog stays in sync.
            const fresh = await api.adminUserGet(selectedUser.id);
            setSelectedUser(fresh);
          }}
          onDeleted={async () => {
            closeUser();
            await refresh();
          }}
        />
      )}
    </AdminPage>
  );
}

const ROLES: ReadonlyArray<{ key: RoleFilter; label: MessageKey }> = [
  { key: "", label: "adminUsers.anyRole" },
  { key: "user", label: "common.roleUser" },
  { key: "admin", label: "common.roleAdmin" },
  { key: "external", label: "common.roleExternal" },
];

const UserRow = memo(function UserRow({ user, onPick }: { user: AdminUser; onPick: (u: AdminUser) => void }) {
  const pct = user.storage_quota_bytes ? Math.min(100, (user.asset_bytes / user.storage_quota_bytes) * 100) : 0;
  const name = user.display_name && user.display_name !== user.email.split("@")[0] ? user.display_name : null;
  return (
    <li className={DATA_ROW}>
      <span
        aria-hidden
        className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-subtle text-meta font-semibold text-text-secondary ring-1 ring-inset ring-border"
      >
        {initials(user.display_name, user.email)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <button
            type="button"
            onClick={() => onPick(user)}
            className="min-w-0 truncate text-left text-item font-medium text-text-primary after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-accent"
          >
            {name ?? user.email}
          </button>
          <Badge tone={user.role === "admin" ? "accent" : "neutral"}>{t(USER_ROLE_LABEL[user.role])}</Badge>
          {user.locked && (
            <Badge tone="warning" icon={<Lock size={12} aria-hidden />}>
              {t("adminUsers.locked")}
            </Badge>
          )}
          {!user.email_verified && <Badge>{t("adminUsers.unverified")}</Badge>}
        </div>
        <p className="mt-0.5 flex flex-wrap gap-x-2 text-meta text-text-secondary">
          {name && <span className="truncate font-code">{user.email}</span>}
          <span>{t(AUTH_METHOD_LABEL[user.auth_method])}</span>
          <span className="lg:hidden">
            · {tn("adminUsers.documentCount", user.asset_count)} · {formatBytes(user.asset_bytes)}
          </span>
        </p>
      </div>
      <div className="hidden w-44 shrink-0 lg:block">
        <p className="text-meta tabular-nums text-text-secondary">
          {tn("adminUsers.documentCount", user.asset_count)} · {formatBytes(user.asset_bytes)}
        </p>
        <div
          className="mt-1 h-1 overflow-hidden rounded-full bg-surface-subtle"
          role="progressbar"
          aria-label={t("quota.usage")}
          aria-valuenow={Math.round(pct)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div className={clsx("h-full rounded-full", pct >= 90 ? "bg-danger" : pct >= 75 ? "bg-warning" : "bg-accent")} style={{ width: `${pct}%` }} />
        </div>
      </div>
      <p className="hidden w-40 shrink-0 text-meta text-text-secondary md:block">
        {user.last_login_at ? t("adminUsers.lastLogin", { when: formatRelative(user.last_login_at) }) : t("adminUsers.neverLoggedIn")}
      </p>
      <ChevronRight size={16} aria-hidden className="shrink-0 text-text-tertiary" />
    </li>
  );
});

export type { AdminUser };
