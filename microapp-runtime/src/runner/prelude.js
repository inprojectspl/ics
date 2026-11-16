// Guest-side SDK (js-capabilities-v1), evaluated inside every fresh QuickJS
// context before the handler module. It only marshals JSON to the single host
// function; every rule (capabilities, row scope, fields, conditions, revision)
// is enforced again by the broker, so a handler that rewrites this object
// gains nothing.
export const GUEST_PRELUDE = String.raw`
(function () {
  "use strict";
  const call = globalThis.__ics_call;
  delete globalThis.__ics_call;
  const rpc = (method, args) => call(method, JSON.stringify(args)).then((text) => JSON.parse(text));
  const deepFreeze = (value) => {
    if (value && typeof value === "object") {
      Object.values(value).forEach(deepFreeze);
      Object.freeze(value);
    }
    return value;
  };
  class IcsError extends Error {
    constructor(status, code, message) {
      super(message || code);
      this.name = "IcsError";
      this.status = status;
      this.code = code;
    }
  }
  const logLevels = ["info", "warn", "error"];
  globalThis.__ics_make = function (inputText, ctxText) {
    const input = deepFreeze(JSON.parse(inputText));
    const base = JSON.parse(ctxText);
    const ctx = {
      actor: base.actor,
      app: base.app,
      request: base.request,
      db: {
        get: (collection, id, options) => rpc("db.get", [collection, id, options || {}]),
        list: (collection, query, options) => rpc("db.list", [collection, query || {}, options || {}]),
        insert: (collection, data, options) => rpc("db.insert", [collection, data, options || {}]),
        update: (collection, id, patch, options) => rpc("db.update", [collection, id, patch, options || {}]),
        delete: (collection, id, options) => rpc("db.delete", [collection, id, options || {}]).then(() => undefined),
        count: (collection, filters, options) => rpc("db.count", [collection, filters || [], options || {}]),
        groupCount: (collection, field, filters, options) =>
          rpc("db.groupCount", [collection, field, filters || [], options || {}]),
      },
      errors: {
        notFound: () => new IcsError(404, "not_found", "not found"),
        forbidden: (code) => new IcsError(403, String(code || "forbidden")),
        conflict: (code) => new IcsError(409, String(code || "conflict")),
        invalid: (code) => new IcsError(422, String(code || "validation_failed")),
      },
      log: (level, message, fields) => {
        if (!logLevels.includes(level)) level = "info";
        call("log", JSON.stringify([level, String(message).slice(0, 500), fields || {}]));
      },
    };
    deepFreeze(ctx.actor);
    deepFreeze(ctx.app);
    deepFreeze(ctx.request);
    Object.freeze(ctx.db);
    Object.freeze(ctx.errors);
    Object.freeze(ctx);
    return { input, ctx };
  };
})();
`;
