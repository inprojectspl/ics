import { useCallback, useState } from "react";
import type { UploadShareMode } from "../api";

const STORAGE_KEY = "ics:default-upload-mode";

export function readStoredUploadMode(): UploadShareMode {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === "public" || v === "org_sso") return v;
  } catch {
    // blocked storage: the organisation default
  }
  return "org_sso";
}

/** Who sees new uploads by default. Sticky across sessions, so someone who
 * routinely publishes externally does not switch it every time. */
export function useUploadMode(): [UploadShareMode, (m: UploadShareMode) => void] {
  const [mode, setMode] = useState<UploadShareMode>(readStoredUploadMode);
  const choose = useCallback((m: UploadShareMode) => {
    setMode(m);
    try {
      window.localStorage.setItem(STORAGE_KEY, m);
    } catch {
      // private window: kept for this session only
    }
  }, []);
  return [mode, choose];
}
