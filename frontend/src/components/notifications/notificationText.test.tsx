import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { setLocale, t } from "../../lib/i18n";
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

describe("a request for access to a linked spreadsheet", () => {
  const item = mkItem({
    code: "sheets.access_requested",
    actor: { id: "u3", name: "Bob" },
    asset: { id: "a9", slug: "requests", title: "Requests", kind: "micro_application" },
    project: null,
    version: null,
    params: { email: "bob@gmail.com" },
    link: "/v/requests?tab=sheets",
  });

  it("names the app in bold and the Google account to share with", () => {
    const text = t("notifications.text.sheetsAccessRequested", { email: "bob@gmail.com" });
    expect(text).toContain("bob@gmail.com");
    expect(notificationPlainText(item)).toBe(text.replace("{title}", "Requests"));
    const { container } = render(<p>{NotificationText({ item })}</p>);
    expect(container.querySelector("strong")).toHaveTextContent("Requests");
    expect(NOTIFICATION_ICON["sheets.access_requested"]).toBeDefined();
  });
});

describe("an automatic sheet sync that stopped", () => {
  const stopped = (params: Record<string, string | number>) =>
    mkItem({
      code: "sheets.auto_sync_stopped",
      actor: null,
      asset: { id: "a9", slug: "requests", title: "Requests", kind: "micro_application" },
      project: null,
      version: null,
      params,
      link: "/v/requests?tab=sheets",
    });

  it("counts the conflicts waiting for a person, with the app in bold", () => {
    const item = stopped({ reason: "conflicts", conflicts: 3 });
    expect(notificationPlainText(item)).toBe("Automatic sync of the sheet linked to Requests is waiting for you: 3 conflicts to decide");
    expect(notificationPlainText(stopped({ reason: "conflicts", conflicts: 1 }))).toContain(": 1 conflict to decide");
    const { container } = render(<p>{NotificationText({ item })}</p>);
    expect(container.querySelector("strong")).toHaveTextContent("Requests");
    expect(NOTIFICATION_ICON["sheets.auto_sync_stopped"]).toBeDefined();
  });

  it("uses Polish plural forms", () => {
    setLocale("pl", { persist: false });
    try {
      const text = (n: number) => notificationPlainText(stopped({ reason: "conflicts", conflicts: n }));
      expect(text(1)).toContain("„Requests” czeka na Ciebie: 1 konflikt do rozstrzygnięcia");
      expect(text(3)).toContain(": 3 konflikty do");
      expect(text(5)).toContain(": 5 konfliktów do");
    } finally {
      setLocale("en", { persist: false });
    }
  });

  it("explains an error by its code, or shows an unknown code as is", () => {
    expect(notificationPlainText(stopped({ reason: "google_no_access", conflicts: 0 }))).toBe(
      "Automatic sync of the sheet linked to Requests stopped: The Google account cannot open this spreadsheet.",
    );
    expect(notificationPlainText(stopped({ reason: "mystery_code", conflicts: 0 }))).toBe(
      "Automatic sync of the sheet linked to Requests stopped: mystery_code",
    );
  });
});
