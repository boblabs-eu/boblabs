# Versioning Policy

Bob Labs follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
once the project reaches **v1.0.0**. Before then (`0.x`), minor releases
can carry breaking changes — we will flag them clearly in the
[CHANGELOG](CHANGELOG.md) and the [UPGRADE](UPGRADE.md) guide.

This document defines **what is public** (covered by the version
contract) and **what is internal** (free to change in any release).
If your integration only touches the public surface, you can rely on
SemVer guarantees from v1.0.0 onward.

---

## What is public

These surfaces are part of the version contract. Breaking changes here
require a major version bump (post-1.0) or a clearly-flagged minor
bump (pre-1.0).

### 1. REST API — `/api/v1/*`

Every endpoint under `/api/v1/*` exposed by the control-plane
([`control-plane/app/api/routes/`](control-plane/app/api/routes/)) —
request shapes, response shapes, status codes, query parameters,
authentication requirements.

The contract is canonically expressed as [`docs/openapi.json`](docs/openapi.json),
auto-exported from the FastAPI app on every release (drift-checked in CI).

### 2. Consumer-app HMAC envelope

The headers and signing convention used by `/api/v1/internal/apps/*`:

- `X-App-Id` — registered consumer-app identifier
- `X-App-Timestamp` — Unix epoch seconds, ±300s window
- `X-App-Signature` — HMAC-SHA256 of `app_id + timestamp + body`, hex-encoded

See [`docs/CONSUMER_APPS.md`](docs/CONSUMER_APPS.md) for the full
contract and rotation policy.

### 3. Lab blueprint JSON shape

The Pydantic schemas that define a lab — what gets stored in the
`labs.definition` JSONB column. Authoritative source:
[`control-plane/app/models/orchestrator.py`](control-plane/app/models/orchestrator.py)
and [`control-plane/app/schemas/orchestrator.py`](control-plane/app/schemas/orchestrator.py).
A lab blueprint exported as `.lab.json` from one version must boot on
the same major version.

### 4. WebSocket event types

The set of event types broadcast over `/ws/client`, their payload
shapes, and audience-scoping rules. Enumerated in
[`docs/API_REFERENCE.md`](docs/API_REFERENCE.md).

### 5. Skill files convention

The frontmatter shape and lookup path for `templates/skills/<name>.md`.
A skill file written against version `X.Y.0` will resolve and load on
any later release of the same major version.

### 6. Environment variables

The names, types, and meanings of variables documented in
[`.env.example`](.env.example). Adding a new env var with a sensible
default is a minor bump; renaming or removing one is a major bump
(post-1.0).

### 7. Database schema

Alembic revisions are monotonic and forward-only. No destructive
renames or column drops happen in a patch or minor release without a
deprecation window. See [`UPGRADE.md`](UPGRADE.md) for per-version
schema notes.

### 8. CLI / deploy scripts

The interfaces exposed by:

- [`deploy-prod.sh`](deploy-prod.sh) — flags, env-var inputs, exit codes
- `docker-compose.yml` service names + exposed ports

Renaming a service or changing its port is a major bump.

---

## What is internal

Free to change anytime, including in patch releases:

- Python module layout, import paths inside `app.*`
- Function signatures of helpers and private utilities
- Repository classes (`*_repo.py`) — public consumers go through routes, not directly through SQLAlchemy
- Frontend component structure (React component names, file paths under `frontend/src/`)
- Migration file numbering (we won't renumber, but the migrations themselves are implementation details)
- Internal services (`app/services/*`) — exposed only via routes
- Log line formats (use the audit log, not stdout, for stable integration)
- Default values that aren't documented in `.env.example`
- Anything in `templates/lab_examples/*.lab.json` — these are examples, not API surface

If a third-party library imports from `app.*` directly, that's a
non-supported integration pattern — please open an issue describing
the use case so we can promote the right surface to public.

---

## Deprecation policy

When a public surface needs to be removed or renamed:

1. **Mark deprecated** — in the next minor release, the surface is
   tagged in the code (`@deprecated` decorator, `Deprecation` HTTP
   response header, warning log line) and called out in the CHANGELOG
   under `### Deprecated`.
2. **Sunset window** — at least **one full minor release** between
   deprecation and removal. For example, deprecate in `1.3.0`, remove
   no earlier than `1.4.0`.
3. **Removal** — happens in a major release (post-1.0) or is flagged
   as breaking in a 0.x minor release (pre-1.0).

Security fixes that remove a vulnerable surface are exempt from the
sunset window but will be clearly documented.

---

## SemVer mapping for this project

Concrete examples of what bumps which segment:

| Change | Pre-1.0 (current) | Post-1.0 |
|---|---|---|
| Bug fix, no behavior change | PATCH (`0.10.0 → 0.10.1`) | PATCH |
| New REST endpoint, additive | MINOR (`0.10.0 → 0.11.0`) | MINOR |
| New env var with a default | MINOR | MINOR |
| New field on existing response | MINOR | MINOR |
| New event type on WebSocket | MINOR | MINOR |
| New schema migration (additive only) | MINOR | MINOR |
| Removing an endpoint | MINOR (flagged as breaking) | MAJOR |
| Renaming an HMAC header | MINOR (flagged) | MAJOR |
| Changing the shape of a lab blueprint field | MINOR (flagged) | MAJOR |
| Schema migration that drops a column | MINOR (flagged) | MAJOR |
| Renaming a docker-compose service | MINOR (flagged) | MAJOR |

---

## When does v1.0 land?

When all of these are true:

1. The Tier 1 release artifacts are stable (CI green, install verified, OpenAPI committed and drift-tested).
2. At least **two consecutive minor releases** ship without a regression in the install verification.
3. We've absorbed **4–6 weeks of public issue traffic** without surfacing structural API problems.
4. There are no known breaking changes queued.

Until then, every `0.x.y` release is a step toward that promise.

---

## Reporting compatibility concerns

If a release breaks something on a surface you thought was public —
open an issue with the `compat` label. Either we made a mistake (and
will roll back / fix), or the surface wasn't supposed to be public
(and we'll document it explicitly here).

For security-sensitive compatibility issues, follow
[SECURITY.md](SECURITY.md) instead.
