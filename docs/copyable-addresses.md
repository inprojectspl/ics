# Copyable asset addresses

An HTML bundle and a micro-application run on their own origin
(`html.<domain>/<slug>/...`, `https://<name>.<app suffix>/...`) and know the
visitor by a cookie of that origin. Without more, the address in the bar does
not say which share link the visit came through, so a copied address works
for the sender (who has the cookie) and not for the recipient. ICS keeps the
link in the address instead: decision in
[ADR-0030](decisions/0030-copyable-share-addresses.md).

## The `ics_share` parameter

```text
https://html.example.net/report/costs.html?tab=results&ics_share=TOKEN#summary
https://k7m2q9x4.apps.example.net/?ics_share=TOKEN#/settings?tab=account
```

- `TOKEN` is the token of an existing share link (`/s/TOKEN`), never a
  cookie, a launch code, an OAuth token or the personal `m` of an e-mail link.
- At most one `ics_share` per address. A repeated parameter (even with the
  same value) or a malformed token is refused by the server and ignored by
  the script; no other link is picked in its place.
- It sits in the query, before `#`. The fragment, a hash router's own
  `#/route?x=1` and the app's other parameters (order, repeats, encoding)
  stay as they were.
- It names the link, it does not grant anything. The server checks it on
  every page load: a live link (not revoked or expired; a link that used its
  last open still serves the visit that open allowed) of exactly this asset.

## What the visitor's browser does

ICS (bundles) and the broker (micro-applications) insert one external,
classic script into the `<head>` of every served HTML page, before the
page's own scripts and after its charset declaration:

```html
<script src="https://html.example.net/_/share-context.js" data-asset-id="..."
  data-kind="html_bundle" data-scope="/report/" data-entry-mode="continuation"></script>
```

The source is `backend/app/static/share_context.js`; the broker serves the
same file at `/__ics/share-context.js` (fetched from ICS, kept 5 minutes). The
script renders nothing and makes no requests. It:

- adds the link to `href` of links to other pages of the same asset (the
  same origin and, for a bundle, its `/<slug>/` prefix; `.html`/`.htm`, and
  extensionless routes of an app), so a plain click, a middle click, a new
  tab and *Copy link address* all carry it. Local anchors (`#x`), other
  origins, other assets, `mailto:`, files, `/api/` and `/__ics/` stay
  untouched, and so does a link whose author put an `ics_share` in it;
- does the same for links added or changed later (a `MutationObserver`
  over the changed nodes only) and checks a link once more right before it
  is used;
- adds the link to URLs given to `history.pushState` / `replaceState`
  (state, the omitted URL and native errors are kept);
- adds one `ics_share` to the data of a GET form submitted to a page of the
  asset (the `formdata` event; POST and other targets are left alone);
- keeps the link of the visit in `sessionStorage` of the tab and the asset
  (`ics:share-context:v1:<asset>`). A page of the same visit whose address
  lost the parameter (`location.href = ...`) gets it back with
  `replaceState`, without a new history entry. A history traversal restores
  that entry's own link instead, and an entry without one stays without one.
- exposes `window.icsShareContext.withContext(href)` for code that opens a
  new tab itself (`window.open` is not covered automatically).

An open from the ICS panel without a link is a *direct* entry: the next page
gets `data-entry-mode="direct"` once (a one-minute cookie set by the grant or
the app sign-in) and the script drops the tab's earlier link context.

## Entry without a session

A page requested without a valid session (a recipient's first visit, an
expired cookie, a link that is not the one the cookie was issued for) is
answered with a small entry page instead: status 401, no content of the
asset, `no-store`, `Referrer-Policy: no-referrer`, only the script with
`data-entry-mode="recover"`. The script keeps the whole address, fragment
included, in the tab and sends the browser:

- with a link (from the address, else from the tab's context): to the
  link's own entry, `/s/<token>?to=<page>` for a bundle and
  `/__ics/share?token=<token>&to=<page>` for an app, where ICS applies the
  link's password, sign-in, recipient list, expiry and open limit;
- without one: an app starts the usual ICS sign-in (`/__ics/login`), a
  bundle page asks to open the document from its link.

After the gate the visit returns to the page (`to`, checked to stay inside
the asset: no absolute or network paths, dot or empty segments, control
characters or their encoded forms, no gateway routes) with the link in its
address, and the script puts the fragment back. At most two tries per address
within a minute, so a browser that refuses cookies does not loop.

A member who opens a link keeps their own access (they are never demoted to
an anonymous visitor), and their address keeps the link. A link visitor
whose cookie belongs to another link goes through the new link's entry. The
open limit is counted once per entry, as before: fixing an address, moving
between pages and running the script again never spend an open.

## Operation

- `ICS_SHARE_CONTEXT_ENABLED` (default `true`) switches the injection for
  both ICS and the broker (the broker reads it from ICS on every request).
  Turned off, addresses that already carry `ics_share` keep working: the
  checks and the entry page stay.
- The token is visible to the asset's JavaScript and in the address, like
  `/s/<token>` is. It never goes to other assets or origins, every response
  on the way keeps `Referrer-Policy: no-referrer`, and pages and entry pages
  are `no-store`. Reverse proxies that log query strings log it, as they log
  `/s/<token>` paths; drop the query from access logs if that matters.
- Not covered: code that removes the script, JavaScript turned off, a new
  tab opened by `window.open` without `withContext`, and an old address
  without `ics_share` opened by someone with no context of their own.
- Browser check on the local profile, Chromium and WebKit:
  `local/microapps/acceptance/share_context.py`.
