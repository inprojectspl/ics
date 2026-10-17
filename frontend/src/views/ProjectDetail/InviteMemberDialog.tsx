import { useState, type FormEvent } from "react";
import { clsx } from "clsx";
import { t, type MessageKey } from "../../lib/i18n";
import { Field, INPUT_CLASS } from "../../components/Field";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";

type Role = "editor" | "viewer";

const ROLES: ReadonlyArray<{ value: Role; label: MessageKey; body: MessageKey }> = [
  { value: "editor", label: "common.roleEditor", body: "projectMembers.editorBody" },
  { value: "viewer", label: "common.roleViewer", body: "projectMembers.viewerBody" },
];

interface Props {
  projectName: string;
  busy: boolean;
  /** Resolves true when the invitation went out. */
  onInvite: (email: string, role: Role) => Promise<boolean>;
  onClose: () => void;
}

/** Invite by e-mail, with what each role may do spelled out. */
export function InviteMemberDialog({ projectName, busy, onInvite, onClose }: Props) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("editor");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    if (await onInvite(email.trim(), role)) onClose();
  };

  return (
    <Dialog title={t("projectMembers.inviteTitle")} eyebrow={projectName} onClose={onClose} maxWidth="lg">
      <form onSubmit={submit} className="space-y-4 px-5 py-5 sm:px-6">
        <Field label={t("common.email")}>
          <input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT_CLASS} />
        </Field>
        <fieldset>
          <legend className="mb-1.5 text-ui font-medium text-text-primary">{t("common.role")}</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {ROLES.map((r) => (
              <label
                key={r.value}
                className={clsx(
                  "flex cursor-pointer gap-3 rounded-card border p-3 transition-colors duration-150",
                  role === r.value ? "border-accent bg-accent-soft" : "border-border hover:bg-surface-hover",
                )}
              >
                <input
                  type="radio"
                  name="invite-role"
                  checked={role === r.value}
                  onChange={() => setRole(r.value)}
                  className="mt-0.5 size-4 shrink-0 accent-accent"
                />
                <span>
                  <span className="block text-ui font-medium text-text-primary">{t(r.label)}</span>
                  <span className="block text-meta text-text-secondary">{t(r.body)}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" busy={busy} disabled={!email.trim()}>
            {t("common.invite")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
