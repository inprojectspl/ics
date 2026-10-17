# Architectural Decision Records (ADRs)

Architecture and product decisions for ICS. Every decision that changes "how we build" or "what we build" goes here as a numbered Markdown file.

## Why

- **Git-tracked**. A decision is a commit: versioned and searchable.
- **Searchable**. `git log --grep="ADR-NNNN"` gives the full context.
- **Keeps the code clean**. No 20-line "decision pending" comments in `main.py`. A code comment is at most a 2-3 line pointer to the ADR.
- **Forces discipline**. Writing an ADR means thinking through the options and their cost; debt cannot be parked "for later".

## Status lifecycle

| Status      | Meaning |
|-------------|---------|
| `Pending`   | Not decided yet. Code may be in a temporary state (e.g. a commented-out router). Work is limited to the described scope. |
| `Accepted`  | Decided. The ADR describes what we did and why. The code follows the decision. |
| `Superseded by NNNN` | Replaced by a newer ADR. The old one stays, to show what we used to think. |
| `Rejected`  | Considered and rejected. Kept so nobody proposes the same thing again in six months. |

## Format

See `0001-comments-feature-deferred.md` as the template. Sections:

1. **Status** + decision owners + scope (which files it affects)
2. **Context**: what happened that requires a decision
3. **Problem**: what exactly does not work or needs settling
4. **Decision** (with options 1/2/3 and estimates in hours or days)
5. **Reactivation trigger**: which event forces a return to the topic
6. **Consequences**: what the current state takes away and what it adds
7. **References**: commits, files, links to discussions

## Numbering

Numbers start at `0001`. Numbers are never reused (not even from deleted ADRs). A new number is the current `max + 1`.

## ADR list

- [ADR-0001](0001-comments-feature-deferred.md): Comments feature, rejected and removed.
- [ADR-0002](0002-quality-bar.md): Quality bar (10/10 ratchet): what "high standard" means in ICS.
- [ADR-0003](0003-dependency-major-upgrades.md): Major dependency upgrades (React 19, TS 6, shiki 4, ...) and a backend refresh.
- [ADR-0004](0004-version-preview-readonly.md): Archived version preview is read-only and separate from restore.
- [ADR-0005](0005-link-hierarchy.md): Link hierarchy: `/v/<slug>` resolves to an access channel.
- [ADR-0006](0006-rendered-markdown-cache.md): Rendered Markdown cache keyed by asset version.
- [ADR-0007](0007-liberal-password-policy.md): Liberal password policy, strength shown instead of enforced.
- [ADR-0008](0008-mit-license.md): MIT license.
- [ADR-0009](0009-english-first-with-ui-i18n.md): English first, UI translated through i18n.
- [ADR-0010](0010-ui-i18n.md): UI i18n with a typed in-house `t()` and flat JSON catalogues.
- [ADR-0011](0011-backend-i18n.md): Backend message catalogue (pl, en) and locale resolution.
- [ADR-0012](0012-unified-app-navigation.md): One navigation model for every signed-in page. Superseded by ADR-0024.
- [ADR-0013](0013-pdf-assets.md): PDF as an asset kind, with its text served as Markdown.
- [ADR-0014](0014-office-documents.md): Word and OpenDocument text as an asset kind, served as Markdown.
- [ADR-0015](0015-asset-metadata-model.md): Asset metadata model: typed columns plus JSONB, doc type vocabulary, computed freshness.
- [ADR-0016](0016-asset-relation-graph.md): Asset relation graph in PostgreSQL: eight relation types, extraction from content, graph access per step.
- [ADR-0017](0017-project-shares.md): Project shares: an asset assigned to several projects as a fifth role source.
- [ADR-0018](0018-external-references.md): External references: OpenProject work package as the task identity, project mapping and key documents.
- [ADR-0019](0019-agent-context-pack.md): Agent context pack: one call with ordering, token budget and freshness signals.
- [ADR-0020](0020-personal-access-tokens.md): Personal access tokens for Project Standard: read only, no admin bypass, enforced scopes.
- [ADR-0021](0021-document-ocr.md): OCR of scanned PDF pages, local engine behind a provider interface.
- [ADR-0022](0022-pdf-reader.md): PDF reader on pdf.js' viewer components, with full screen.
- [ADR-0023](0023-notifications.md): Notifications: watches in PostgreSQL, inbox in Redis, in-app, browser push, e-mail and Google Chat.
- [ADR-0024](0024-app-shell-and-design-system.md): App shell and design system v2: one sidebar navigation, token-only styling, reader inspector, Anime.js motion.
- [ADR-0025](0025-graph-explorer.md): Graph explorer: an incremental walk through the document graph from projects or one document.
