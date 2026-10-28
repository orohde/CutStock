# Security Policy

## Supported versions

Only the latest release of CutStock receives security fixes. Please update to the
newest version (desktop app or `ghcr.io/orohde/cutstock:latest`) before reporting.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Instead, report it privately via GitHub:
**[Security -> Report a vulnerability](https://github.com/orohde/CutStock/security/advisories/new)**

Helpful details:

- CutStock version and variant (desktop app, Docker, from source)
- What an attacker can do and how to reproduce it
- Whether the instance must be reachable from outside your network

You'll get a response as soon as possible. CutStock is a one-person project, so
please allow a few days.

## Scope

CutStock's web app is **single-user by design** and has no built-in login. The
optional API key only protects the REST API. Running CutStock openly on the
internet without a reverse proxy, SSO, or VPN in front of it is not a supported
setup -- missing authentication in that scenario is not considered a
vulnerability.

In scope, for example:

- Bypassing the API key
- Code execution, path traversal, or file access via uploads, imports (JSON/CSV),
  or backups
- Cross-site scripting through material names, project data, or similar input
