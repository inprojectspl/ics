import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { SecurityReport } from "../api";
import { t } from "../lib/i18n";
import { FindingsList, SecurityFindings, commonFolder, groupFindings, severityCounts } from "./SecurityFindings";

type Finding = SecurityReport["findings"][number];
const f = (over: Partial<Finding>): Finding => ({ severity: "warn", rule: "r", file: "a.html", line: 1, message: "m", ...over });

describe("groupFindings", () => {
  it("groups by rule, the most severe and the most frequent first, places sorted", () => {
    const groups = groupFindings([
      f({ severity: "info", rule: "meta", file: "b.html" }),
      f({ severity: "info", rule: "meta", file: "a.html" }),
      f({ severity: "info", rule: "meta", file: "a.html", line: null }),
      f({ severity: "warn", rule: "inline" }),
      f({ severity: "critical", rule: "eval", file: "x.js", line: 9 }),
      f({ severity: "info", rule: "lonely" }),
    ]);
    expect(groups.map((g) => g.rule)).toEqual(["eval", "inline", "meta", "lonely"]);
    expect(groups[2]?.places).toEqual([
      { file: "a.html", line: null },
      { file: "a.html", line: 1 },
      { file: "b.html", line: 1 },
    ]);
  });
});

describe("commonFolder", () => {
  it("finds the folder every finding sits in", () => {
    expect(commonFolder([f({ file: "dist/a/x.html" }), f({ file: "dist/a/y/z.html" })])).toBe("dist/a/");
    expect(commonFolder([f({ file: "dist/x.html" }), f({ file: "other/y.html" })])).toBe("");
    expect(commonFolder([f({ file: "index.html" })])).toBe("");
    expect(commonFolder([])).toBe("");
  });
});

describe("severityCounts", () => {
  it("counts each severity", () => {
    expect(severityCounts([f({ severity: "critical" }), f({ severity: "info" }), f({ severity: "info" })])).toEqual({
      critical: 1,
      warn: 0,
      info: 2,
    });
  });
});

describe("FindingsList", () => {
  it("caps the places until asked for all, keeping each group's full count", () => {
    const findings = Array.from({ length: 5 }, (_, i) => f({ rule: "meta", message: "refresh", file: `p/${i}.html` }));
    render(<FindingsList findings={findings} limit={2} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: t("securityFindings.showAll", { count: 5 }) }));
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.queryByRole("button", { name: /Show all/ })).not.toBeInTheDocument();
  });

  it("says when a finding covers the whole file", () => {
    render(<FindingsList findings={[f({ line: null, file: "a.html" })]} />);
    expect(screen.getByText(new RegExp(t("securityFindings.wholeFile")))).toBeInTheDocument();
  });
});

describe("SecurityFindings", () => {
  const report: SecurityReport = { status: "critical", findings: [f({ severity: "critical" })] };

  it("stays hidden when clean, bypassed or empty", () => {
    const { container, rerender } = render(<SecurityFindings status="clean" report={report} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<SecurityFindings status="critical" report={report} bypassed />);
    expect(container).toBeEmptyDOMElement();
    rerender(<SecurityFindings status="critical" report={{ status: "critical", findings: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("alerts with the heading of the status", () => {
    const { rerender } = render(<SecurityFindings status="critical" report={report} />);
    expect(screen.getByRole("alert")).toHaveTextContent(t("securityFindings.criticalHeading"));
    rerender(<SecurityFindings status="warn" report={report} />);
    expect(screen.getByRole("alert")).toHaveTextContent(t("securityFindings.warnHeading"));
  });
});
