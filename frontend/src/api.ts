// Aggregates all domain modules under a single `api` object and re-exports
// the types for backward compatibility. Components still use `api.X()`.
// New code should import from the module directly, e.g.
//   import { listAssets } from "./api/assets";
// for better tree-shaking and clearer scope.

import * as admin from "./api/admin";
import * as assets from "./api/assets";
import * as auth from "./api/auth";
import * as bindings from "./api/bindings";
import * as projects from "./api/projects";
import * as relations from "./api/relations";
import * as shares from "./api/shares";

export { encodePath, postJson, req } from "./api/_core";
export type * from "./api/types";

export const api = {
  ...auth,
  ...assets,
  ...shares,
  ...projects,
  ...bindings,
  ...relations,
  ...admin,
};
