# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- First public release.
- Documentation site at <https://inprojectspl.github.io/ics/>, built with MkDocs from `docs/`.

### Security

- A single Markdown upload or a new version of one stores the file under its base name, so a
  name with directory segments cannot write into another document.
- Bundle files served on the app origin (the legacy `/static/` links of documents and shares)
  are sandboxed and cannot call the API with the visitor's session.

### Fixed

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
