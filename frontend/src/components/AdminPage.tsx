import type { ReactNode } from "react";
import { ShieldOff } from "lucide-react";
import type { Me } from "../api";
import { t } from "../lib/i18n";
import { EmptyState } from "./EmptyState";
import { Page } from "./shell/Page";
import { ADMIN_SCREENS, type AdminTab } from "./shell/navModel";
import { PageContext } from "./shell/PageContext";

interface Props {
  me: Me;
  tab: AdminTab;
  children: ReactNode;
}

/**
 * Frame of every administration screen: the breadcrumb and one content
 * width. The screens are linked from the sidebar, so there is no second
 * tab strip repeating them. A non-admin gets the no-access notice; the API
 * refuses them anyway.
 */
export function AdminPage({ me, tab, children }: Props) {
  return (
    <>
      <PageContext crumbs={[{ label: t("nav.admin"), href: "/admin/users" }, { label: t(ADMIN_SCREENS.find((s) => s.tab === tab)?.label ?? "nav.admin") }]} />
      {me.role !== "admin" ? (
        <Page width="form">
          <EmptyState icon={ShieldOff} title={t("admin.noAccessTitle")} description={t("admin.noAccessBody")} />
        </Page>
      ) : (
        <Page>{children}</Page>
      )}
    </>
  );
}
