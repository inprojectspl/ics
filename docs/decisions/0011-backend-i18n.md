# ADR-0011: Backend message catalogue and locale resolution

**Status:** Accepted, 2026-09-24.
**Decision owners:** Owner.
**Scope:** `backend/app/i18n/`, `backend/app/email_templates.py`,
`backend/app/services/notifications/`, `backend/app/services/version_banner.py`,
`backend/app/oauth/server/authorize.py`, `backend/app/bundle_scan/`,
`users.locale` (migration 0030), `PATCH /api/auth/me`.

## Context

ADR-0009 makes English the project language and requires user-facing
e-mails and notifications to be rendered per locale. Besides e-mails, the
backend produces other text that people read without the frontend in
between: Google Chat cards, the archived-version banner injected into HTML
bundles, the OAuth consent page and the security scanner findings. All of
it was Polish only.

## Problem

1. Where the translations live and how they are looked up.
2. Which locale a given text is rendered in, when the reader is not always
   the one making the request (an invitation e-mail, a chat card sent from
   CI).
3. Scanner findings are persisted in `assets.security_report` and read
   later, possibly by someone with a different language.

## Decision

### Catalogue

`app/i18n/en.json` and `app/i18n/pl.json`: flat objects of dotted keys
(`email.invite.subject`, `scan.eval_call`). `t(key, locale, **params)`
returns plain text, `t_html` the HTML-escaped form (parameters wrapped in
`SafeHtml` are inserted as they are), `tn` picks a plural form
(`key.one` / `key.few` / `key.many`). An unknown locale or a key missing
in one locale falls back to English.

Placeholders are `{name}` only and are substituted with a regex, not with
`str.format`, so a catalogue value can never reach an attribute or index of
a parameter.

Options considered:

1. **gettext (`.po`/`.mo`) or Babel.** Standard tooling and plural rules,
   but a compile step, a new dependency and a format nobody else in the
   repository uses. About 100 strings do not justify it.
2. **Python dicts per locale.** No I/O, but translators edit code, and the
   "no Polish in string literals" test would need a hole for the Polish
   module.
3. **JSON files plus a 150-line module (chosen).** No dependency, the same
   shape as a typical frontend catalogue, easy to diff. Plurals are limited
   to the forms Polish and English need.

Tests keep the catalogues in sync: identical key sets, no empty values, the
same placeholders in every locale, and a `scan.<code>` key for every scanner
rule.

API error `detail` is not part of the catalogue: clients translate API
errors by `code` (ADR-0009). Operator-facing messages (startup errors,
OpenAPI descriptions, log lines) are English and not translated.

### Locale resolution

`resolve_locale(*stored, accept_language=...)`: the first supported stored
locale, then the request's `Accept-Language` (q-values honoured), then
English. Routes take the header as `accept_language: AcceptLanguage = None`
(`app/i18n/request.py`), so they can still be called directly without a
request object.

- `users.locale` (nullable, `pl` or `en`) is the user's explicit choice,
  set through `PATCH /api/auth/me` and returned by `GET /api/auth/me`.
  NULL means "follow the browser". An unsupported value is a 422
  `validation_error`.
- E-mails: the recipient's stored locale, then the sender's stored locale,
  then the sender's request language. A recipient without an account (new
  invitee, external magic-link address) therefore gets the sender's
  language, or English.
- Chat cards are sent during a CI sync, which has no browser: the binding
  author's locale, then the asset owner's, then English.
- The archived-version banner is served on the isolated bundle origin
  without an ICS session: `Accept-Language` only. HTML documents there are
  `no-store`, so no cache can hand one language to another reader.
- The OAuth consent page: the user's locale, then `Accept-Language`.

### Scanner findings

A finding is stored as `rule`, `code`, `params` (for example
`{"host": "evil.cdn"}`), severity, file and line; no text. `code` is the
catalogue key suffix and usually equals `rule`
(`external_script_src_trusted` is the one variant). Every endpoint that
returns a report (`/doc`, the admin review queue, the MCP `/security`
endpoint) passes it through `bundle_scan.localize_report`, which adds
`message` in the reader's locale. The response shape stays the same for
the frontend and `ics-mcp`: findings still have `message`, and `code` and
`params` are new fields.

Rows scanned before this change have Polish `message` and no `code`.
They are not migrated: every new upload or sync rescans the bundle and
overwrites the report. Until then, findings whose message needs no
parameters are rendered from the rule name; the external-host finding and
findings of retired rules keep their stored text.

## Reactivation trigger

A third locale, plural rules that the three forms cannot express, or
translators asking for a standard format (`.po`, XLIFF). Any of these is a
reason to move to Babel.

## Consequences

- A new user-facing backend string means a key in both JSON files; the
  parity test fails otherwise.
- A new scanner rule needs a `scan.<rule>` key in both files.
- New routes that produce such text take `AcceptLanguage` and call
  `resolve_locale` with the stored locales of the people involved.
- `tests/test_english_source.py` rejects Polish characters in string
  literals under `backend/app`, so translations cannot creep back into
  code.
- Doc type labels (`doc_types.label_pl`, `label_en`) are data stored in the
  database, not user-facing backend text, so they are not in
  `app/i18n/{en,pl}.json`; a response carries both labels or the one
  matching the resolved locale. See [ADR-0015](0015-asset-metadata-model.md).
