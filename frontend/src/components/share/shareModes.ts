import { Building2, Globe2, KeyRound, MailCheck, type LucideIcon } from "lucide-react";
import type { ShareMode } from "../../api";
import type { MessageKey } from "../../lib/i18n";

interface ModeInfo {
  label: MessageKey;
  hint: MessageKey;
  icon: LucideIcon;
}

export const MODE_INFO: Record<ShareMode, ModeInfo> = {
  org_sso: { label: "shareDialog.modeOrgSso", hint: "shareDialog.hintOrgSso", icon: Building2 },
  magic_email: { label: "shareDialog.modeMagicEmail", hint: "shareDialog.hintMagicEmail", icon: MailCheck },
  password: { label: "common.password", hint: "shareDialog.hintPassword", icon: KeyRound },
  public: { label: "shareDialog.modePublic", hint: "shareDialog.hintPublic", icon: Globe2 },
};

/** Link modes in the order a person weighs them: narrowest audience first. */
export const SHARE_MODE_ORDER: readonly ShareMode[] = ["org_sso", "magic_email", "password", "public"];
