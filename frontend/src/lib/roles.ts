import type { AdminUser, ProjectRole, UserRole } from "../api";
import type { MessageKey } from "./i18n";

/** Catalogue keys of role names; the API sends the raw values. */
export const PROJECT_ROLE_LABEL: Record<ProjectRole, MessageKey> = {
  owner: "common.roleOwner",
  editor: "common.roleEditor",
  viewer: "common.roleViewer",
};

export const USER_ROLE_LABEL: Record<UserRole, MessageKey> = {
  admin: "common.roleAdmin",
  user: "common.roleUser",
  external: "common.roleExternal",
};

type AuthMethod = AdminUser["auth_method"];

/** Short sign-in method label for the users list. */
export const AUTH_METHOD_LABEL: Record<AuthMethod, MessageKey> = {
  google_sso: "adminUsers.authGoogle",
  password: "common.password",
  invite: "adminUsers.authInvite",
};

/** Sign-in method as the user detail dialog spells it out. */
export const SIGN_IN_LABEL: Record<AuthMethod, MessageKey> = {
  google_sso: "adminUsers.authGoogle",
  password: "userDetail.emailPassword",
  invite: "userDetail.signInInvite",
};
