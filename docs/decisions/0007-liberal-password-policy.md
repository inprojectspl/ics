# ADR-0007: Liberal password policy, strength shown instead of enforced

**Status:** Accepted, implemented 2026-09-22.
**Decision owners:** Owner, prompted by a team report.
**Scope:** `backend/app/passwords.py`, password fields in the frontend
(`ShareDialog`, `Setup`, `ResetConfirm`), new
`frontend/src/lib/passwordStrength.ts` and `components/PasswordStrength.tsx`.

## Context

The previous rule: at least 12 characters and characters from at least 3 of
4 categories (lowercase, uppercase, digits, special characters). The same
function validated account passwords and share link passwords.

The team report was about a link password: a short password made from the
company name was already blocked by the browser, and after appending the year
the backend rejected it with a message about character categories. Two
rejections in a row for a task that comes down to sending someone a link and
a password over a separate channel.

## Problem

Composition rules are costly and work poorly. They push people towards short,
predictable substitutions such as `Password2026!`, because that is the
cheapest way to satisfy the checklist, while rejecting long passphrases that
are much harder to guess. NIST stopped recommending composition rules in 2017
for exactly this reason.

On top of that there is the product context: a link password is not an
account credential. It protects a single document, is passed to the recipient
over a separate channel and lives as long as the link. Treating it like an
account password is not justified by the risk.

Options considered:

1. **Split the policy: loose for links, strict for accounts.** Addresses the
   report, but keeps the flawed rule where it hurts just as much, and adds two
   validation paths to maintain.
2. **Keep the rules, soften the messages.** Does not solve the problem, only
   describes it more nicely.
3. **A single liberal policy: a minimum length, no composition rules, and
   strength shown in the interface.** In line with current guidance, one
   validation path, and the decision stays with the person.

## Decision

Option 3. `MIN_LENGTH` drops from 12 to 8 and the character category rule is
gone. The Pydantic models read the same constant, so they adjusted by
themselves.

The frontend gets a strength meter: four segments, a label and a one-sentence
hint. It is purely informational and never blocks submission. The score is an
approximate entropy (length times the log of the alphabet size), with
penalties for what actually makes guessing easier:

- passwords from guessing lists, compared in three forms (as typed, without
  decorations, reduced to the stem), so `Zaq12wsx!` lands where `zaq12wsx`
  does;
- a word with an appended year or a few digits counts little more than the
  word alone;
- repetitions and keyboard sequences buy no strength.

A passphrase of several words is scored per word, so
`mug of tea on the windowsill` comes out stronger than `P@ss1!`, which matches
reality and which the old rule could not express.

We do not use `zxcvbn`: with its dictionary the library weighs several hundred
kilobytes and would land in the application's entry bundle. Our own heuristic
fits in a few kilobytes and is tested separately as a pure function.

## Reactivation trigger

Revisit this decision when:

- ICS starts storing data covered by an external standard that mandates
  password composition rules;
- sign-in without a second factor appears for accounts with elevated
  privileges, and a risk analysis identifies the password as a single point of
  failure. The direction then is to require a second factor, not to go back to
  composition rules;
- an audit shows that users widely set passwords rated as very weak. Then
  raise the minimum length first, and only then consider anything else.

## Consequences

- Existing account passwords remain valid. The change only affects validation
  when a new password is set.
- A shorter minimum with unchanged Argon2id (64 MB memory, time_cost 3) and
  account lockout after a series of failed attempts. Remote attacks are still
  limited by the lockout, not by password composition.
- MCP is not affected: it passes the password to the backend and does not
  describe the requirements anywhere, so it needs no new release or
  marketplace update.
