// Share-link context of an asset page: keeps the `ics_share` token of the
// link a visit started from in the address bar and in links to the asset's
// own pages, so a copied address takes its recipient through that same link.
// Served on the asset's origin by ICS (HTML bundles) and the broker
// (micro-applications); contract in docs/copyable-addresses.md.
// It renders nothing and makes no requests: it only edits URLs.
(function () {
  "use strict";

  var PARAM = "ics_share";
  var TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;
  var RETURN_TTL_MS = 15 * 60 * 1000;
  var RECOVER_WINDOW_MS = 60 * 1000;
  var RECOVER_MAX_TRIES = 2;

  // ---------- pure URL rules (also loaded by the runtime tests) ----------

  function decodePart(text) {
    try {
      return decodeURIComponent(text.replace(/\+/g, " "));
    } catch (e) {
      return text;
    }
  }

  function paramName(part) {
    var eq = part.indexOf("=");
    return decodePart(eq < 0 ? part : part.slice(0, eq));
  }

  /** `{state: "none"}`, `{state: "one", token}` or `{state: "invalid"}` for a
   * query string (with or without `?`): repeated or malformed is invalid. */
  function readToken(search) {
    var query = search.charAt(0) === "?" ? search.slice(1) : search;
    var found = [];
    if (query) {
      var parts = query.split("&");
      for (var i = 0; i < parts.length; i++) {
        if (paramName(parts[i]) !== PARAM) continue;
        var eq = parts[i].indexOf("=");
        found.push(eq < 0 ? "" : decodePart(parts[i].slice(eq + 1)));
      }
    }
    if (found.length === 0) return { state: "none" };
    if (found.length > 1 || !TOKEN_RE.test(found[0])) return { state: "invalid" };
    return { state: "one", token: found[0] };
  }

  /** `raw` with exactly one `ics_share=token` before the fragment (or none
   * for a null token). Other parameters keep their text and order. */
  function setToken(raw, token) {
    var h = raw.indexOf("#");
    var pre = h < 0 ? raw : raw.slice(0, h);
    var hash = h < 0 ? "" : raw.slice(h);
    var q = pre.indexOf("?");
    var path = q < 0 ? pre : pre.slice(0, q);
    var all = q < 0 || q === pre.length - 1 ? [] : pre.slice(q + 1).split("&");
    var kept = all.filter(function (p) {
      return p !== "" && paramName(p) !== PARAM;
    });
    if (!token && kept.length === all.length) return raw;
    if (token) kept.push(PARAM + "=" + token);
    return path + (kept.length ? "?" + kept.join("&") : "") + hash;
  }

  function stripForCompare(href) {
    var h = href.indexOf("#");
    return setToken(h < 0 ? href : href.slice(0, h), null);
  }

  /** Whether a path names a page of the app, not a script, style or image. */
  function isDocumentPath(pathname, kind) {
    var last = pathname.slice(pathname.lastIndexOf("/") + 1);
    var dot = last.lastIndexOf(".");
    var ext = dot < 0 ? "" : last.slice(dot + 1).toLowerCase();
    if (ext === "html" || ext === "htm") return true;
    return kind === "micro_application" && ext === "";
  }

  var EXCLUDED = { micro_application: ["/api/", "/__ics/"], html_bundle: ["/_/"] };

  /** The URL a reference points to when it is a page of this asset. */
  function assetPage(raw, env) {
    var url;
    try {
      url = new URL(raw, env.base);
    } catch (e) {
      return null;
    }
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    if (url.origin !== env.origin || url.pathname.indexOf(env.scope) !== 0) return null;
    var excluded = EXCLUDED[env.kind] || [];
    for (var i = 0; i < excluded.length; i++) {
      if (url.pathname.indexOf(excluded[i]) === 0) return null;
    }
    return isDocumentPath(url.pathname, env.kind) ? url : null;
  }

  /** `raw` carrying the token when it leads to another page of this asset
   * without naming a token itself; anything else comes back unchanged. */
  function decorate(raw, token, env) {
    if (raw == null || !token) return raw;
    var text = String(raw).trim();
    if (text === "" || text.charAt(0) === "#") return raw;
    var url = assetPage(text, env);
    if (url === null) return raw;
    // Same document, other fragment: a local anchor, left to the browser.
    if (url.href.split("#")[0] === env.here.split("#")[0]) return raw;
    if (readToken(url.search).state !== "none") return raw;
    return setToken(text, token);
  }

  var core = {
    readToken: readToken,
    setToken: setToken,
    isDocumentPath: isDocumentPath,
    decorate: decorate,
  };

  if (typeof document === "undefined") {
    globalThis.IcsShareContextCore = core;
    return;
  }

  // ---------- page bootstrap ----------

  var script = document.currentScript;
  if (!script || window.icsShareContext) return;
  var data = script.dataset;
  var assetId = data.assetId;
  if (!assetId) return;
  var scope = data.scope || "/";
  var kind = data.kind;
  var ctxKey = "ics:share-context:v1:" + assetId;
  var returnKey = "ics:share-return:v1:" + assetId;
  var launchKey = "ics:share-launch:v1:" + assetId;

  function load(key) {
    try {
      var raw = window.sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }
  function save(key, value) {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      // Storage off or full: explicit addresses still carry the context.
    }
  }
  function drop(key) {
    try {
      window.sessionStorage.removeItem(key);
    } catch (e) {
      // As above.
    }
  }
  function storedToken() {
    var rec = load(ctxKey);
    return rec && rec.v === 1 && TOKEN_RE.test(rec.token) ? rec.token : null;
  }
  function remember(token) {
    if (token) save(ctxKey, { v: 1, token: token });
    else drop(ctxKey);
  }

  function env() {
    return { origin: location.origin, scope: scope, kind: kind, base: document.baseURI, here: location.href };
  }

  var navigationType;
  try {
    var nav = performance.getEntriesByType("navigation")[0];
    navigationType = nav && nav.type;
  } catch (e) {
    navigationType = undefined;
  }
  // A history traversal restores that entry's own context; storage is only
  // the fallback for a new page of the same visit.
  var traversed = navigationType === "back_forward";
  var here = readToken(location.search);

  if (data.entryMode === "recover") {
    recover();
    return;
  }

  // ---------- context of this page ----------

  if (data.entryMode === "direct" && data.launch && load(launchKey) !== data.launch) {
    // A fresh open from the ICS panel ends the earlier link visit, once per
    // launch: a later explicit token in this document is not reset again.
    drop(ctxKey);
    save(launchKey, data.launch);
  }
  var token = null;
  if (here.state === "one") {
    token = here.token;
    remember(token);
  } else if (here.state === "none" && !traversed) {
    token = storedToken();
  }

  var nativePush = history.pushState;
  var nativeReplace = history.replaceState;

  if (token && here.state === "none" && assetPage(location.href, env())) {
    nativeReplace.call(history, history.state, "", setToken(location.href, token));
  }
  restoreFragment();

  // ---------- links ----------

  var LINKS = "a[href],area[href]";
  var marks = new WeakMap();
  var decorated = 0;

  function isLink(el) {
    return (el.localName === "a" || el.localName === "area") && el.hasAttribute("href");
  }

  // Remembers which href this script wrote, so its own decoration follows a
  // context change while a token the author put in the link stays.
  function apply(el, e) {
    var current = el.getAttribute("href");
    var mark = marks.get(el);
    var base = mark && current === mark.mine ? mark.orig : current;
    var desired = decorate(base, token, e);
    if (desired === base) {
      if (mark) {
        marks.delete(el);
        decorated--;
        if (current !== base) el.setAttribute("href", base);
      }
      return;
    }
    if (desired !== current) el.setAttribute("href", desired);
    if (!mark) decorated++;
    marks.set(el, { orig: base, mine: desired });
  }

  // Nothing to add and nothing of ours to take back: skip the work.
  function idle() {
    return !token && decorated === 0;
  }

  function applyAll() {
    if (idle()) return;
    var e = env();
    var links = document.querySelectorAll(LINKS);
    for (var i = 0; i < links.length; i++) apply(links[i], e);
  }

  // Only the nodes that changed, one environment per batch.
  new MutationObserver(function (records) {
    if (idle()) return;
    var e = env();
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r.type === "attributes") {
        // Our own write comes back as a mutation: nothing to redo.
        var mark = marks.get(r.target);
        if (isLink(r.target) && !(mark && r.target.getAttribute("href") === mark.mine)) apply(r.target, e);
        continue;
      }
      for (var j = 0; j < r.addedNodes.length; j++) {
        var n = r.addedNodes[j];
        if (n.nodeType !== 1) continue;
        if (isLink(n)) apply(n, e);
        if (n.firstElementChild) {
          var inner = n.querySelectorAll(LINKS);
          for (var k = 0; k < inner.length; k++) apply(inner[k], e);
        }
      }
    }
  }).observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
  applyAll();

  // Last check right before a link is used, copied or opened elsewhere:
  // pointerdown comes before a click, middle click, drag or context menu of
  // a pointer, focusin before a keyboard activation, click for el.click().
  function beforeUse(event) {
    if (idle()) return;
    var el = event.target && event.target.closest ? event.target.closest(LINKS) : null;
    if (el) apply(el, env());
  }
  ["pointerdown", "focusin", "contextmenu", "click"].forEach(function (type) {
    window.addEventListener(type, beforeUse, true);
  });

  // ---------- GET forms ----------

  var submitting = null;
  window.addEventListener(
    "submit",
    function (event) {
      submitting = { form: event.target, submitter: event.submitter || null, event: event };
      setTimeout(function () {
        submitting = null;
      }, 0);
    },
    true,
  );
  // The entry list of a real submission, not a FormData the app builds.
  window.addEventListener(
    "formdata",
    function (event) {
      var s = submitting;
      if (!token || !s || s.form !== event.target || s.event.defaultPrevented) return;
      var form = s.form;
      var sub = s.submitter;
      var method = (sub && sub.hasAttribute("formmethod") ? sub.getAttribute("formmethod") : form.getAttribute("method")) || "get";
      if (method.toLowerCase() !== "get") return;
      var action = (sub && sub.hasAttribute("formaction") ? sub.getAttribute("formaction") : form.getAttribute("action")) || location.href;
      if (!assetPage(action, env()) || event.formData.has(PARAM)) return;
      event.formData.append(PARAM, token);
    },
    true,
  );

  // ---------- History API ----------

  function wrap(native) {
    return function (state, unused, url) {
      if (arguments.length < 3 || url === undefined || url === null || !token) {
        return native.apply(this, arguments);
      }
      return native.call(this, state, unused, decorate(String(url), token, env()));
    };
  }
  history.pushState = wrap(nativePush);
  history.replaceState = wrap(nativeReplace);

  function syncWithEntry() {
    var entry = readToken(location.search);
    var next = entry.state === "one" ? entry.token : null;
    remember(next);
    if (next !== token) {
      token = next;
      applyAll();
    }
  }
  window.addEventListener("popstate", syncWithEntry);
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) syncWithEntry();
  });

  Object.defineProperty(window, "icsShareContext", {
    value: Object.freeze({
      /** `href` with the current link context, for code that opens a new
       * tab itself (window.open is not covered automatically). */
      withContext: function (href) {
        return decorate(String(href), token, env());
      },
    }),
  });

  // ---------- recovery (entry page without a session) ----------

  function fill(template, value, to) {
    return template.replace("{token}", encodeURIComponent(value)).replace("{to}", encodeURIComponent(to));
  }

  function recover() {
    Object.defineProperty(window, "icsShareContext", { value: Object.freeze({}) });
    if (here.state === "invalid") return;
    var t = here.state === "one" ? here.token : traversed ? null : storedToken();
    var href = location.href;
    var prev = load(returnKey);
    var fresh = prev && prev.href === href && Date.now() - prev.at < RECOVER_WINDOW_MS;
    var tries = fresh ? prev.tries || 0 : 0;
    if (tries >= RECOVER_MAX_TRIES) return;
    // The fragment never reaches a server: kept here until the visit is back.
    save(returnKey, { v: 1, href: href, at: Date.now(), tries: tries + 1 });
    var path = location.pathname.indexOf(scope) === 0 ? location.pathname.slice(scope.length) : "";
    var to = setToken(path + location.search, null);
    var next = t && data.recoverShare ? fill(data.recoverShare, t, to) : data.recoverLogin ? fill(data.recoverLogin, "", to) : null;
    if (next) location.replace(next);
  }

  function restoreFragment() {
    var pending = load(returnKey);
    if (!pending) return;
    drop(returnKey);
    if (Date.now() - pending.at > RETURN_TTL_MS || typeof pending.href !== "string") return;
    if (stripForCompare(pending.href) !== stripForCompare(location.href)) return;
    var h = pending.href.indexOf("#");
    if (h >= 0 && !location.hash) nativeReplace.call(history, history.state, "", location.href + pending.href.slice(h));
  }
})();
