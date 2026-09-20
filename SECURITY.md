# Security policy

## Reporting a vulnerability

Report vulnerabilities privately to `security@thijsvanessen.nl` with:

- a description of the problem;
- steps to reproduce and the impact;
- relevant logs, without sensitive data.

Do not open a public issue or discussion, and do not publish a proof of concept, until a fix
is available. You get an acknowledgement within five working days.

## Supported versions

The current state of `main`. Reports about older forks or releases are handled only when they
affect `main`.

## Scope notes

- The API is read-only apart from watches, relationship voting and the curation endpoint;
  curation is protected by one shared key (`LAWGRAPH_CURATION_API_KEY`), not by user
  accounts.
- Credentials belong in `.env`, which is not committed.
