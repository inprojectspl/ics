import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { t } from "../../lib/i18n";
import { projectRoleName } from "../../lib/roles";
import { mkItem } from "../../test-notifications";
import { NOTIFICATION_ICON, NotificationText, notificationPlainText } from "./notificationText";

describe("a project invitation", () => {
  const item = mkItem({
    code: "project.invited",
    asset: null,
    project: { slug: "crm", name: "CRM" },
    version: null,
    params: { role: "editor" },
    link: "/projects/crm/accept",
  });

  it("names the project, in bold, and the role", () => {
    const text = t("notifications.text.invited", { role: projectRoleName("editor") });
    expect(notificationPlainText(item)).toBe(text.replace("{title}", "CRM"));
    const { container } = render(<p>{NotificationText({ item })}</p>);
    expect(container.querySelector("strong")).toHaveTextContent("CRM");
    expect(NOTIFICATION_ICON["project.invited"]).toBeDefined();
  });
});
