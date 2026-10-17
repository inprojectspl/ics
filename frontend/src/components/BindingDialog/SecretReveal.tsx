import { ReactNode } from "react";
import { clsx } from "clsx";
import { useQuery } from "@tanstack/react-query";
import { api, AssetSummary, BindingWithSecret } from "../../api";
import { t } from "../../lib/i18n";
import { qk } from "../../lib/queries";
import { useClipboard } from "../../lib/useClipboard";
import { fill } from "./_rich";

// Shown when the server has no ICS_SYNC_IMAGE, so the snippet stays valid
// YAML but plainly asks for the operator's own image.
export const SYNC_IMAGE_PLACEHOLDER = "<registry>/ics-sync:<tag>";

function useSyncImage(): string {
  const { data } = useQuery({ queryKey: qk.authConfig(), queryFn: api.authConfig });
  return data?.sync_image || SYNC_IMAGE_PLACEHOLDER;
}

interface Props {
  asset: AssetSummary;
  secret: BindingWithSecret;
  onDismiss: () => void;
}

export function SecretReveal({ asset, secret, onDismiss }: Props) {
  const { copy, copiedKey } = useClipboard();
  const syncImage = useSyncImage();
  const endpoint = window.location.origin;

  const icsFile = [
    `# .inprojects.ics`,
    `version: 1`,
    `binding_id: ${secret.id}`,
    `public_key: |`,
    ...secret.public_key.trim().split("\n").map((l) => "  " + l),
    `publish:`,
    `  source: .`,
    `  kind: ${asset.kind}`,
    `  # exclude:`,
    `  #   - "node_modules/**"`,
    `metadata:`,
    `  title: "${asset.title ?? ""}"`,
  ].join("\n");

  const ciSnippet = [
    `ics:sync:`,
    `  stage: deploy`,
    `  image:`,
    `    name: ${syncImage}`,
    `    entrypoint: [""]`,
    `    pull_policy: always`,
    `  tags:`,
    `    - docker`,
    `  rules:`,
    `    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH`,
    `  variables:`,
    `    ICS_ENDPOINT: "${endpoint}"`,
    `  script:`,
    `    - ics-sync --config .inprojects.ics --private-key "@$ICS_PRIVATE_KEY"`,
  ].join("\n");

  return (
    <section className="px-6 py-5">
      <DangerBanner />

      <Step number={1} title={t("secretReveal.step1Title")}>
        <p className="text-ui text-text-primary mb-3">
          {fill(t("secretReveal.step1Where"), {
            path: <strong>Settings → CI/CD → Variables → Add variable</strong>,
          })}
        </p>

        <Block
          title={t("secretReveal.privateKeyBlock")}
          body={secret.private_key}
          onCopy={() => copy(secret.private_key, "priv")}
          copied={copiedKey === "priv"}
          sensitive
        />

        <VariableTable
          rows={[
            { name: "Key", value: "ICS_PRIVATE_KEY", hint: t("secretReveal.varKeyHint") },
            { name: "Value", value: t("secretReveal.varValue"), hint: t("secretReveal.varValueHint") },
            { name: "Type", value: "File", hint: t("secretReveal.varTypeHint") },
            {
              name: "Environment scope",
              value: t("secretReveal.varScope"),
              hint: t("secretReveal.varScopeHint"),
            },
            { name: "Visibility", value: "-", hint: t("secretReveal.varVisibilityHint") },
            { name: "Flags", value: "Protect variable: ON", hint: t("secretReveal.varFlagsHint") },
          ]}
        />

        <Note tone="info">
          {fill(t("secretReveal.fileTypeNote"), {
            path: <Mono>{t("secretReveal.fileTypePath")}</Mono>,
            arg: <Mono>@$ICS_PRIVATE_KEY</Mono>,
            at: <Mono>@</Mono>,
          })}
        </Note>
      </Step>

      <Step number={2} title={t("secretReveal.step2Title")}>
        <p className="text-ui text-text-primary mb-3">
          {fill(t("secretReveal.step2Intro"), {
            id: <Mono>binding_id</Mono>,
            public: <strong>{t("secretReveal.step2Public")}</strong>,
          })}
        </p>

        <Block
          title={t("secretReveal.icsBlock")}
          body={icsFile}
          onCopy={() => copy(icsFile, "ics")}
          copied={copiedKey === "ics"}
        />

        <FieldList
          fields={[
            { name: "version", desc: t("secretReveal.fieldVersion") },
            { name: "binding_id", desc: t("secretReveal.fieldBindingId") },
            { name: "public_key", desc: t("secretReveal.fieldPublicKey") },
            { name: "publish.source", desc: t("secretReveal.fieldSource") },
            {
              name: "publish.kind",
              desc: fill(t("secretReveal.fieldKind"), {
                collection: <Mono>md_collection</Mono>,
                single: <Mono>md_single</Mono>,
                bundle: <Mono>html_bundle</Mono>,
                kind: <Mono>{asset.kind}</Mono>,
              }),
            },
            { name: "publish.exclude", desc: t("secretReveal.fieldExclude") },
            { name: "metadata.title", desc: t("secretReveal.fieldTitle") },
          ]}
        />
      </Step>

      <Step number={3} title={t("secretReveal.step3Title")}>
        <Block
          title={t("secretReveal.ciBlock")}
          body={ciSnippet}
          onCopy={() => copy(ciSnippet, "ci")}
          copied={copiedKey === "ci"}
        />

        <FieldList
          fields={[
            {
              name: "image.name",
              desc: fill(t("secretReveal.fieldImage"), { image: <Mono>{syncImage}</Mono> }),
            },
            { name: "image.entrypoint: [\"\"]", desc: t("secretReveal.fieldEntrypoint") },
            { name: "image.pull_policy: always", desc: t("secretReveal.fieldPullPolicy") },
            { name: "tags: - docker", desc: t("secretReveal.fieldTags") },
            { name: "rules", desc: t("secretReveal.fieldRules") },
            {
              name: "ICS_ENDPOINT",
              desc: fill(t("secretReveal.fieldEndpoint"), {
                endpoint: <Mono>{endpoint}</Mono>,
                variable: <Mono>$ICS_ENDPOINT</Mono>,
              }),
            },
            {
              name: '--private-key "@$ICS_PRIVATE_KEY"',
              desc: fill(t("secretReveal.fieldPrivateKey"), {
                at: <Mono>@</Mono>,
                name: <Mono>ICS_PRIVATE_KEY</Mono>,
                plain: <Mono>"$ICS_PRIVATE_KEY"</Mono>,
              }),
            },
          ]}
        />

        <Note tone="info">
          {fill(t("secretReveal.jobNote"), {
            lead: <strong>{t("secretReveal.jobNoteLead")}</strong>,
            source: <Mono>publish.source</Mono>,
            url: (
              <Mono>
                {endpoint}/api/bindings/{secret.id}/sync
              </Mono>
            ),
          })}
        </Note>
      </Step>

      <Diagnostics endpoint={endpoint} bindingId={secret.id} />

      <div className="mt-5 flex justify-end">
        <button
          onClick={onDismiss}
          className="text-ui text-text-tertiary hover:text-text-primary"
        >
          {t("secretReveal.dismiss")}
        </button>
      </div>
    </section>
  );
}

function DangerBanner() {
  return (
    <div className="flex items-start gap-3 p-4 mb-6 rounded-control border border-warning/40 bg-warning/[0.06]">
      <svg
        width="24"
        height="24"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-warning shrink-0 mt-0.5"
      >
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3z" />
        <path d="M12 9v4" />
        <path d="M12 17h.01" />
      </svg>
      <div>
        <p className="font-semibold text-warning mb-1">
          {t("secretReveal.bannerTitle")}
        </p>
        <p className="text-ui text-text-primary">
          {fill(t("secretReveal.bannerBody"), {
            rotate: <em>{t("bindingRow.rotate")}</em>,
            file: <Mono>.inprojects.ics</Mono>,
          })}
        </p>
      </div>
    </div>
  );
}

function Step({
  number,
  title,
  children,
}: {
  number: number;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="mb-6">
      <h3 className="text-ui font-semibold text-text-primary mb-3 flex items-baseline gap-2">
        <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-accent text-surface text-meta font-bold shrink-0">
          {number}
        </span>
        <span>{title}</span>
      </h3>
      <div className="ml-8">{children}</div>
    </div>
  );
}

function Block({
  title,
  body,
  onCopy,
  copied,
  sensitive,
}: {
  title: string;
  body: string;
  onCopy: () => void;
  copied: boolean;
  sensitive?: boolean;
}) {
  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-1">
        <p className="text-meta text-text-secondary font-medium">
          {title}
        </p>
        <button
          onClick={onCopy}
          className="text-meta text-accent hover:underline"
        >
          {copied ? t("secretReveal.copied") : t("secretReveal.copy")}
        </button>
      </div>
      <pre
        className={clsx(
          "font-code text-meta text-text-primary p-3 rounded-control overflow-x-auto whitespace-pre",
          sensitive
            ? "bg-danger/[0.04] border border-danger/30"
            : "bg-surface border border-border",
        )}
      >
        {body}
      </pre>
    </div>
  );
}

function VariableTable({
  rows,
}: {
  rows: { name: string; value: string; hint: string }[];
}) {
  return (
    <div className="mb-4 rounded-control border border-border overflow-x-auto">
      <table className="w-full text-ui">
        <thead className="bg-surface border-b border-border">
          <tr>
            <th className="text-left px-3 py-2 text-meta text-text-secondary font-medium">
              {t("secretReveal.colField")}
            </th>
            <th className="text-left px-3 py-2 text-meta text-text-secondary font-medium">
              {t("secretReveal.colValue")}
            </th>
            <th className="text-left px-3 py-2 text-meta text-text-secondary font-medium">
              {t("secretReveal.colNote")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.name} className={clsx("align-top", i < rows.length - 1 && "border-b border-border")}>
              <td className="px-3 py-2 font-code text-meta text-text-primary whitespace-nowrap">
                {r.name}
              </td>
              <td className="px-3 py-2 font-code text-meta text-text-primary">{r.value}</td>
              <td className="px-3 py-2 text-meta text-text-tertiary">{r.hint}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FieldList({
  fields,
}: {
  fields: { name: string; desc: ReactNode }[];
}) {
  return (
    // Names are CLI messages and long URLs sit in the notes: both columns may
    // break anywhere, the names take at most 40%, and phones stack them.
    <dl className="mb-4 grid grid-cols-1 gap-x-3 gap-y-1 text-meta sm:grid-cols-[fit-content(40%)_minmax(0,1fr)] sm:gap-y-2">
      {fields.map((f) => (
        <div key={f.name} className="contents">
          <dt className="font-code text-text-primary [overflow-wrap:anywhere]">{f.name}</dt>
          <dd className="pb-2 text-text-tertiary [overflow-wrap:anywhere] sm:pb-0">{f.desc}</dd>
        </div>
      ))}
    </dl>
  );
}

function Note({ tone, children }: { tone: "info" | "warn"; children: ReactNode }) {
  return (
    <div
      className={clsx(
        "rounded-control border p-3 text-meta mb-4 [overflow-wrap:anywhere]",
        tone === "info" && "border-accent/30 bg-accent/[0.04] text-text-primary",
        tone === "warn" && "border-warning/40 bg-warning/[0.06] text-text-primary",
      )}
    >
      {children}
    </div>
  );
}

function Mono({ children }: { children: ReactNode }) {
  return <code className="font-code text-text-primary">{children}</code>;
}

function Diagnostics({ endpoint, bindingId }: { endpoint: string; bindingId: string }) {
  const syncImage = useSyncImage();
  return (
    <div className="mb-2">
      <h3 className="text-ui font-semibold text-text-primary mb-3">{t("secretReveal.diagnostics")}</h3>
      <div className="ml-0">
        <FieldList
          fields={[
            { name: "403 bad signature", desc: t("secretReveal.diag403") },
            {
              name: "404 Not Found",
              desc: fill(t("secretReveal.diag404"), {
                id: <Mono>binding_id</Mono>,
                file: <Mono>.inprojects.ics</Mono>,
                url: (
                  <Mono>
                    {endpoint}/api/bindings/{bindingId}
                  </Mono>
                ),
              }),
            },
            { name: "409 replay or out-of-order", desc: t("secretReveal.diag409") },
            { name: "400 manifest invalid", desc: t("secretReveal.diag400") },
            // Names quote what ics-sync prints (cmd/ics-sync/main.go, resolvePrivateKey).
            {
              name: "private key: the value after @ is a PEM key, not a file path; pass it without @",
              desc: fill(t("secretReveal.diagNoFile"), {
                name: <Mono>ICS_PRIVATE_KEY</Mono>,
                file: <strong>File</strong>,
                at: <Mono>@</Mono>,
                variable: <Mono>$ICS_PRIVATE_KEY</Mono>,
              }),
            },
            {
              name: "private key: cannot read the key file: no such file or directory",
              desc: fill(t("secretReveal.diagKeyMissing"), { name: <Mono>ICS_PRIVATE_KEY</Mono> }),
            },
            {
              name: t("secretReveal.diagPullName"),
              desc: fill(t("secretReveal.diagPull"), {
                image: <Mono>{syncImage}</Mono>,
                config: <Mono>~/.docker/config.json</Mono>,
              }),
            },
          ]}
        />
      </div>
    </div>
  );
}
