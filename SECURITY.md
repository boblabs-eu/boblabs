# Security policy

Bob Labs runs as infrastructure on your own servers — most deployments handle
private RAG, credentials for LLM providers, GPU agents, and (optionally) Web3
keys. A vulnerability here can have outsized impact, so we take reports
seriously and ask you to disclose them privately first.

## Reporting a vulnerability

**Please do NOT open a public GitHub issue for security-relevant findings.**

Email **support@boblabs.eu** with:

- A short description of the issue and its impact.
- Steps to reproduce (or a proof-of-concept, if you have one).
- The affected component(s) — `bob-api`, `bob-ui`, `bob-agent`, `sandbox`,
  `gpu-services`, etc.
- The commit SHA or release tag you tested against.

We aim to acknowledge every report **within 7 days**, share an initial
severity assessment within **14 days**, and ship a fix or mitigation as
quickly as the issue warrants. If you'd like credit in the fix's commit
message or release notes, say so in the report.

## What counts as a vulnerability

In scope:

- Remote code execution, sandbox escape, or unauthorized container access.
- Authentication or authorization bypass (operator JWT, consumer-app HMAC,
  access tokens).
- Cross-tenant data leakage (RAG collections, lab workspaces, agent
  memories).
- Secret exposure through logs, error responses, or admin UIs.
- SQL injection, SSRF, or path traversal against any HTTP endpoint.
- LLM prompt-injection paths that reach a privileged tool (e.g. `shell_exec`,
  `trading`, `mail.send`).

Out of scope:

- Findings that require operator-level access you already have (the
  operator is trusted; that is the trust model).
- Best-practice suggestions ("you should rotate JWTs every 7 days") without
  a concrete exploit.
- Denial-of-service via raw resource exhaustion — labs are CPU/GPU-bound
  by design; the right knobs are rate limits and quotas in your reverse
  proxy / orchestrator.
- End-of-life version compromises — please test against `main` or the
  latest release tag.

## Coordinated disclosure

We follow standard coordinated disclosure: we ask reporters to wait until a
fix has shipped (or 90 days have passed, whichever comes first) before
publishing details. We will work with you to align on timing if the issue
is being actively exploited.

Thanks for helping keep Bob Labs deployments safe.
