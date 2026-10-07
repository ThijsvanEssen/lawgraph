# Security policy

## Reporting a vulnerability

Report vulnerabilities privately to `security@thijsvanessen.nl` with:

- a description of the problem;
- steps to reproduce and the impact;
- relevant logs, without sensitive data.

Do not open a public issue or discussion, and do not publish a proof of concept, until a fix
is available. You get an acknowledgement within five working days.

## Supported versions

The latest release on `main`. A report about a fork or an older release is handled only when it
affects that release.

## Scope notes

- The API is read-only: it answers `GET`, `HEAD` and `OPTIONS` and has no accounts.
- Credentials belong in `.env`, which is not committed.
