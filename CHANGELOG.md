# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- First public release.
- Documentation site at <https://inprojectspl.github.io/ics/>, built with MkDocs from `docs/`.
- `format=markdown` on an agent read of a Markdown file (`file-mcp`, `agent-view`, share
  `resolve`) drops its HTML comments, so machine markers such as transcript timestamps do not
  cost tokens; comments in code stay and every line keeps its number.

### Changed

- `format=markdown` on a file that is neither HTML nor Markdown answers `format_unsupported`
  instead of `html_only`.

### Security

- `POST /api/assets/{id}/undelete` on a document that is not deleted answers `404` to anyone
  but its owner, instead of returning its slug.
- An HTML bundle created through `POST /api/assets/html-json`, as MCP does, counts against the
  owner's total storage quota like every other upload.
- An OAuth token, as used by MCP clients, never carries administrator rights, like a personal
  access token: an admin's agent sees what an ordinary user would and `/api/admin/*` refuses it.
  Administration stays in the browser.
- A refresh token or authorization code used by two requests at once is consumed once: the
  second request waits for the first and is refused, so one refresh no longer yields two live
  successors.
- Revoking a refresh token works without `token_type_hint` or with a wrong one, and ends the
  grant: the token's rotation family and the access tokens issued with it stop working at once.
  Reuse of a rotated refresh token cuts the access tokens of its family too.
- The loopback redirect of the built-in stdio client is checked as a parsed URL, so only the
  port may vary: `http://127.0.0.1:1@other.host/callback` no longer sends the authorization code
  to another host. Dynamic clients register only HTTPS, loopback HTTP or app-scheme callbacks, and the
  consent page shows where the browser goes after consent.
- A single Markdown upload or a new version of one stores the file under its base name, so a
  name with directory segments cannot write into another document.
- Bundle files served on the app origin (the legacy `/static/` links of documents and shares)
  are sandboxed and cannot call the API with the visitor's session.

### Fixed

- OAuth clients can discover the authorization server at the issuer's root; the existing
  discovery URLs under `/api/auth/oauth/` remain supported. Deployments must also forward the
  root discovery paths through their reverse proxy.
- Connecting an MCP client from a signed-out browser resumes the original consent request
  after Google or password sign-in. Google return paths are validated and bound to a single
  OIDC transaction.
- OAuth consent responses preserve the exact client `state`, including reserved characters,
  after either allowing or denying access.
- The agent context pack no longer fails with a server error on a `supersedes` chain of three
  or more documents; the whole chain collapses into its newest visible document.
- Restoring version 1 on S3 or R2 storage no longer copies the files of versions 10 to 19.
- The collection reader shows the last file clicked even when answers arrive out of order, and
  back/forward show the file the address names.
- A new version of a bundle or a collection keeps the `entry_path` the caller names; it was
  ignored and ICS picked `index.html` or `README.md` instead.
- An older GitLab sync that was still uploading when a newer one landed no longer publishes
  over it: the order check is repeated under a lock on the binding.
- The sign-in page retries loading its configuration, so Google sign-in no longer disappears
  until a reload when the page opened while the server was restarting.
