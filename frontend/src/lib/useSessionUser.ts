import { useQuery } from "@tanstack/react-query";
import { api, type Me } from "../api";
import { qk } from "./queries";

/**
 * Signed-in user for views that skip the app-level session probe (the
 * document reader, where link visitors land too). A 401 means "no account
 * menu", not an error, so it is not retried.
 */
export function useSessionUser(enabled = true): Me | null {
  return useQuery({ ...sessionQuery, enabled }).data ?? null;
}

/** The session user query, shared with the router (`App.tsx`), which also
 * needs to tell "not known yet" from "signed out". */
export const sessionQuery = {
  queryKey: qk.me(),
  queryFn: api.me,
  retry: false,
  staleTime: 300_000,
} as const;
