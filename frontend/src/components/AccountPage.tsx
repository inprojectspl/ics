import type { ReactNode } from "react";
import type { Me } from "../api";
import { t, type MessageKey } from "../lib/i18n";
import { PageTabs } from "./PageTabs";
import { Page } from "./shell/Page";
import { PageContext } from "./shell/PageContext";
import { PageHeader } from "./ui/PageHeader";

type AccountTab = "notifications" | "tokens";

const TABS: ReadonlyArray<{ key: AccountTab; href: string; label: MessageKey }> = [
  { key: "notifications", href: "/account/notifications", label: "account.tabNotifications" },
  { key: "tokens", href: "/account/tokens", label: "account.tabTokens" },
];

interface Props {
  me: Me;
  tab: AccountTab;
  children: ReactNode;
}

/** Frame of the personal settings: one heading and local tabs between its
 * two pages (they belong to the settings object, not to the navigation). */
export function AccountPage({ tab, children }: Props) {
  const current = TABS.find((x) => x.key === tab);
  return (
    <>
      <PageContext
        crumbs={[{ label: t("account.title"), href: "/account/notifications" }, { label: current ? t(current.label) : "" }]}
      />
      <Page width="form">
        <PageHeader title={t("account.title")} />
        <PageTabs
          tabs={TABS.map((x) => ({ ...x, label: t(x.label) }))}
          active={tab}
          ariaLabel={t("account.sections")}
          className="mb-8"
        />
        {children}
      </Page>
    </>
  );
}
