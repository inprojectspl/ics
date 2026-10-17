# ADR-0008: MIT license, copyright held by inProjects spółka z o.o. sp.k.

**Status:** Accepted, 2026-09-24. Amended 2026-10-17: the holder changed at the legal owner's request.
**Decision owners:** Owner.
**Scope:** `LICENSE` in `ics`, `ics-mcp` and `ics-sync`, license metadata in
`frontend/package.json`, `backend/pyproject.toml` and `ics-mcp/pyproject.toml`.

## Context

ICS and its MCP server are being prepared for a possible open-source
release. `ics` had no license file (the README said "internal"), while
`ics-mcp` already shipped an MIT `LICENSE`. The copyright
holder was spelled three different ways across `LICENSE`, `pyproject.toml`
and the plugin manifests.

## Problem

A public repository without a license is not open source, and inconsistent
holder names make it unclear who grants the license.

Options considered:

1. **MIT.** Simplest permissive license, already used by `ics-mcp`,
   compatible with every runtime dependency (MPL-2.0 and EPL-2.0 packages
   are only transitive and stay under their own terms).
2. **Apache-2.0.** Adds an explicit patent grant and a NOTICE requirement.
3. **AGPL-3.0.** Would force hosted forks of ICS to publish their changes,
   at the cost of adoption.

## Decision

Option 1. The repositories are licensed under MIT, copyright
"inProjects spółka z o.o. sp.k.". This exact string is the only holder name used in `LICENSE`
files and package metadata (`license`, `authors`); `NOTICE` adds the
company's registered address.

The inProjects and inProjects.ai names and the inProjects.ai logo are not
covered by the MIT License. `NOTICE` in each repository says so, lists the
logo files and allows keeping the "Built by inProjects.ai" credit unchanged;
any other use needs the company's written permission.

## Reactivation trigger

A request from the legal owner to change the holder entity, or a
dependency whose license is incompatible with MIT.

## Consequences

- `ics` gets a root `LICENSE` identical in wording to `ics-mcp`.
- Package metadata and manifests are aligned with the holder name when
  they are next touched for the open-source work.
- Publishing the existing history additionally needs the co-authors'
  consent; that is tracked with the publication task, not here.
