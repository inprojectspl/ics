# Security policy

## Supported versions

ICS does not publish versioned releases yet. Security fixes land on the
latest `main` branch only; please make sure you can reproduce the issue there
before reporting it.

## Reporting a vulnerability

Please do **not** open a public issue or pull request for a security
problem. Report it privately through
[GitHub private vulnerability reporting](https://github.com/inprojectspl/ics/security/advisories/new)
(the **Report a vulnerability** button on the repository's Security tab).

Include as much of the following as you can:

- the affected component (backend, frontend, HTML bundle viewer, OAuth/MCP,
  GitLab binding sync, deployment files) and the commit you tested;
- a description of the issue and its impact (what an attacker can read,
  change or run, and with which privileges);
- step-by-step reproduction, a proof of concept or a failing test;
- any configuration that matters (`ICS_SECURITY_POLICY`, storage backend,
  proxy setup, enabled sign-in methods);
- whether the issue is already public or known to others.

Please do not access data that is not yours, and do not run tests that
degrade service for other users.

## What to expect

- We acknowledge a report within **5 working days**.
- We send an initial assessment (confirmed, needs more information, or not a
  vulnerability) within **15 working days**.
- We keep you updated while a fix is prepared and agree a disclosure date
  with you. Our default is to publish a fix and a short advisory within 90
  days of the report.
- With your permission, we credit you in the advisory and the changelog.

## Scope notes

Some behaviour is intentional and documented:

- HTML bundles run arbitrary JavaScript by design. They are isolated on a
  separate origin (`ICS_HTML_VIEWER_BASE`); a way to reach the main app's
  cookies, API or origin from a bundle **is** in scope.
- `ICS_DEBUG=1` and `ICS_DEV_STUB_SSO` weaken security for local development
  and must never be enabled in production.
