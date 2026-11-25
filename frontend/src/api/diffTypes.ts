// Version comparison: the change list of two versions, one file's diff, and
// for a micro-application what changed in the app itself.

import type { AssetKind, VersionRow } from "./types";

/** One entry of a version comparison, the same shape for every kind.
 * `added_lines`/`removed_lines` are `null` for
 * binary files and for files above the byte threshold (the backend does not
 * diff a minified one-liner). */
export type DiffFileChange = {
  path: string;
  change: "added" | "removed" | "modified";
  binary: boolean;
  added_lines: number | null;
  removed_lines: number | null;
  size_from: number | null;
  size_to: number | null;
};

/** Comparison summary (without `?path=`): one shape for all kinds. A single
 * file's content is fetched separately via `?path=`. */
export type DiffSummary = {
  kind: AssetKind;
  from_version: number;
  to_version: number;
  from_meta: VersionRow | null;
  to_meta: VersionRow | null;
  files: DiffFileChange[];
  /** micro_application only: what changed in the app itself. */
  app_changes?: AppChange[];
};

/** Response for `?path=`: unified diff of one file. */
export type DiffFile = {
  path: string;
  change: "added" | "removed" | "modified";
  diff: string;
};

/** One change in the app's terms (a role gained a permission, a collection
 * got a field). */
export type AppChange = {
  area: "role" | "permission" | "endpoint" | "capability" | "collection" | "setting" | "realtime_channel" | "external_host";
  name: string;
  change: "added" | "removed" | "changed";
  /** `+a -b` for sets, otherwise the manifest keys that differ. */
  detail: string;
};
