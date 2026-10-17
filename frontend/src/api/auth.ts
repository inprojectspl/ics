import { patchJson, postJson, req } from "./_core";
import type { AccessToken, AuthConfig, CreatedAccessToken, Me, Quota } from "./types";

export const me = () => req<Me>("/api/auth/me");
// The backend uses the saved language for e-mails sent to this user.
export const setMyLocale = (locale: Me["locale"]) => patchJson<Me>("/api/auth/me", { locale });
export const myQuota = () => req<Quota>("/api/auth/me/quota");
export const authConfig = () => req<AuthConfig>("/api/auth/config");

// ---------- Personal access tokens (ADR-0020) ----------

export const listTokens = () => req<{ items: AccessToken[] }>("/api/auth/tokens");

export const createToken = (name: string, expiresAt: string) =>
  postJson<CreatedAccessToken>("/api/auth/tokens", { name, expires_at: expiresAt });

export const revokeToken = (id: string) =>
  req<void>(`/api/auth/tokens/${id}`, { method: "DELETE" });

export const login = (email: string, password: string) =>
  postJson<{ ok: boolean }>("/api/auth/login", { email, password });

export const logout = () => req<{ ok: boolean }>("/api/auth/logout", { method: "POST" });

export const passwordResetRequest = (email: string) =>
  postJson<{ ok: boolean }>("/api/auth/password-reset/request", { email });

export const passwordResetConfirm = (token: string, newPassword: string) =>
  postJson<{ ok: boolean }>("/api/auth/password-reset/confirm", {
    token,
    new_password: newPassword,
  });

export const setupFromToken = (token: string, password: string, displayName?: string) =>
  postJson<{ ok: boolean }>("/api/auth/setup", {
    token,
    password,
    display_name: displayName,
  });
