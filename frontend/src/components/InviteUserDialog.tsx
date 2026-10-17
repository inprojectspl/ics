import { FormEvent, useState } from "react";
import { clsx } from "clsx";
import { api } from "../api";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { INPUT_CLASS } from "./Field";

interface Props {
  onClose: () => void;
  onCreated: () => void | Promise<void>;
}

/** Admin invite form (POST /api/admin/users): the regular invite flow plus
 * the role chosen up front. */
export function InviteUserDialog({ onClose, onCreated }: Props) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<"user" | "external" | "admin">("user");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.adminUserInvite({
        email: email.trim().toLowerCase(),
        display_name: displayName.trim() || null,
        role,
      });
      await onCreated();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog eyebrow={t("inviteUser.eyebrow")} title={t("inviteUser.title")} onClose={onClose} maxWidth="xl">
      <form onSubmit={submit} className="px-6 py-5 space-y-4">
        <p className="text-meta text-text-tertiary">
          {t("inviteUser.intro")}
        </p>

        <label className="block">
          <span className="mb-1.5 block text-ui font-medium text-text-primary">
            {t("common.email")}
          </span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="alice.smith@example.org"
            className={clsx(INPUT_CLASS, "font-code")}
          />
        </label>

        <label className="block">
          <span className="mb-1.5 block text-ui font-medium text-text-primary">
            {t("inviteUser.displayName")}
          </span>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Alice Smith"
            className={INPUT_CLASS}
          />
        </label>

        <fieldset>
          <legend className="text-meta text-text-secondary mb-2 font-medium">
            {t("common.role")}
          </legend>
          <div className="space-y-2">
            <RoleOption
              value="user"
              checked={role === "user"}
              onSelect={() => setRole("user")}
              title={t("inviteUser.roleUser")}
              desc={t("inviteUser.roleUserDesc")}
            />
            <RoleOption
              value="external"
              checked={role === "external"}
              onSelect={() => setRole("external")}
              title={t("inviteUser.roleExternal")}
              desc={t("inviteUser.roleExternalDesc")}
            />
            <RoleOption
              value="admin"
              checked={role === "admin"}
              onSelect={() => setRole("admin")}
              title={t("inviteUser.roleAdmin")}
              desc={t("inviteUser.roleAdminDesc")}
            />
          </div>
        </fieldset>

        {error && <p className="text-ui text-danger">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" busy={busy} disabled={!email.trim()}>
            {busy ? t("common.sending") : t("inviteUser.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function RoleOption({
  value,
  checked,
  onSelect,
  title,
  desc,
}: {
  value: string;
  checked: boolean;
  onSelect: () => void;
  title: string;
  desc: string;
}) {
  return (
    <label
      className={clsx(
        "flex items-start gap-3 p-3 rounded-control border cursor-pointer",
        checked ? "border-accent bg-accent-soft/30" : "border-border hover:border-text-tertiary",
      )}
    >
      <input
        type="radio"
        name="role"
        value={value}
        checked={checked}
        onChange={onSelect}
        className="mt-1 accent-accent shrink-0"
      />
      <span>
        <span className="block font-medium text-text-primary">{title}</span>
        <span className="block text-meta text-text-tertiary mt-0.5">{desc}</span>
      </span>
    </label>
  );
}
