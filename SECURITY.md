# Security Policy

## Supported versions

Life Dashboard is a personal project with a single release line. Only the
latest commit on the `main` branch receives security fixes.

| Version        | Supported |
| -------------- | --------- |
| `main` (latest) | ✅        |
| Anything older  | ❌        |

## Reporting a vulnerability

**Please do not open a public issue, pull request or discussion for security
problems.**

Report vulnerabilities privately through GitHub's private vulnerability
reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the issue, the affected file(s) or endpoint(s), steps to
   reproduce, and the impact you expect.

Direct link: <https://github.com/alienbrainfarm/life-dashboard/security/advisories/new>

### What to expect

- An acknowledgement within **7 days**.
- An initial assessment (confirmed / not reproducible / out of scope) within
  **14 days**.
- For confirmed issues, a fix on `main` and a published GitHub Security
  Advisory, crediting you unless you'd rather stay anonymous.

This is a hobby project maintained in spare time, so timelines are best-effort.
There is no bug bounty.

## Scope

In scope:

- The Flask app (`app/`, `run.py`) and its REST and MCP endpoints
- Authentication and authorisation (`app/auth.py`: IAP JWT, API key, Bearer token)
- The MCP server (`mcp_server.py`) and the scripts in `scripts/` and `functions/`
- Deployment configuration in this repo (`Dockerfile`, `deploy/`)

Out of scope:

- Vulnerabilities in third-party dependencies with no demonstrated impact on
  this project (please report those upstream)
- Problems that need an already-compromised machine or account
- Running the local dev server (`python run.py`) on an untrusted network: it is
  meant for `127.0.0.1` only
- Denial of service through traffic volume

## Hardening notes for self-hosters

- Never expose the local dev server to the internet, and never enable
  `FLASK_DEBUG` outside local development.
- Set a strong `API_KEY` for any deployed instance and keep it out of version
  control (`.env` is git-ignored).
- Keep dependencies current (`pip install -U -r requirements.txt`).
