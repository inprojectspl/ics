import type { OcrState } from "../api";
import { messageForCode } from "./errorMessages";
import { hasMessage, t } from "./i18n";

/** Whether a PDF has anything to say about OCR: a scan, or a run on record. */
export function hasOcrState(state: OcrState | null | undefined): state is OcrState {
  return (
    state != null &&
    (state.pages_without_text > 0 ||
      state.pages_with_hidden_text > 0 ||
      state.status !== "not_requested")
  );
}

/** Why a run failed, in words: an OCR code, a document code, or generic. */
export function failureReason(code: string | null): string {
  const key = `ocrStatus.failure.${code ?? "unknown"}`;
  if (hasMessage(key)) return t(key);
  return messageForCode(code) ?? t("ocrStatus.failure.unknown");
}

/** Name of an OCR engine for the reader; an unknown one shows as is. */
export function providerLabel(name: string | null): string {
  const key = `ocrStatus.provider.${name ?? "local"}`;
  return hasMessage(key) ? t(key) : (name ?? "");
}
