# Bob Labs — Access Control & Authorization

## Table of Contents

- [1. Current Authentication System](#1-current-authentication-system)
- [2. Admin Panel](#2-admin-panel)
- [3. Email Notifications](#3-email-notifications)
- [4. User Workflow (End-to-End)](#4-user-workflow-end-to-end)
- [5. Technical Implementation Details](#5-technical-implementation-details)
- [6. Configuration Reference](#6-configuration-reference)
- [7. Authorization & RBAC — Architecture Plan](#7-authorization--rbac--architecture-plan)
- [8. RBAC Implementation Plan](#8-rbac-implementation-plan)

---

## 1. Current Authentication System

### Overview

Bob Labs uses a **token-based access system** where the platform owner controls who can access the application. There is no self-registration — all access is gated through manually generated tokens.

### Authentication Flow

```
User                        Bob Labs                     Admin
 │                            │                            │
 ├── Visit /request-trial ──► │                            │
 │    Fill form (name,email)  │                            │
 │                            ├── Store trial_request ───► │
 │                            ├── Email notification ────► │
 │                            │                            │
 │                            │   Admin reviews at /admin  │
 │                            │ ◄── Generate token ────────┤
 │                            │ ◄── Set expiry (N days) ───┤
 │                            │                            │
 │ ◄── Token email ───────────┤    (auto-sent if email)    │
 │                            │                            │
 ├── Visit /login ──────────► │                            │
 │    Paste token             │                            │
 │                            ├── Validate token           │
 │                            │   (exists, not revoked,    │
 │                            │    not expired)             │
 │ ◄── JWT returned ──────────┤                            │
 │    Stored in localStorage  │                            │
 │                            │                            │
 ├── Access /dashboard ─────► │                            │
 │    JWT in Authorization    │                            │
 │    header (automatic)      │                            │
```

### Token Format

Access tokens follow the format `bob_{base64_urlsafe(32)}` — e.g. `bob_Kx7mN2p...`. They are stored in the `access_tokens` table and validated against expiry and revocation status.

### JWT Payload

When a token is validated, a JWT is issued with:
```json
{
  "sub": "user@example.com",
  "role": "user",
  "exp": 1712856000
}
```

Admin login produces:
```json
{
  "sub": "admin",
  "role": "admin",
  "exp": 1712856000
}
```

JWTs expire after `JWT_EXPIRE_MINUTES` (default: 1440 = 24 hours).

### Public vs Protected Routes

**Nginx** enforces route protection at the proxy level:

| Route Pattern | Auth Required | Description |
|---|---|---|
| `/` `/fr` `/docs` `/login` `/request-trial` `/admin` | No | Public SPA pages |
| `/docs-md/*` | No | Static markdown files |
| `/api/v1/public/*` | No | Public API (trial submit, token validate, admin login) |
| `/api/v1/*` | Yes (Bearer JWT) | All other API endpoints |
| `/ws/*` | Yes (Bearer JWT) | WebSocket connections |

---

## 2. Admin Panel

### Access

The admin panel is available at `/admin` and requires the `ADMIN_SECRET` password (configured in `.env`). Admin authentication is separate from the token system — the admin secret produces a JWT with `role: admin`.

### Features

**Trial Requests Tab:**
- View all trial requests with name, email, company, role, status, date
- Pending requests show "Generate Token" and "Reject" action buttons
- Generating a token auto-creates an access token linked to the user's email
- Optional: auto-send the token to the user via email

**Access Tokens Tab:**
- View all generated tokens with truncated value, label, email, expiry, status
- Status badges: active (green), expired (red), revoked (red)
- "New Token" button for manual token creation (not tied to a trial request)
- "Revoke" button to immediately disable a token

### Admin Session

The admin JWT is stored in `sessionStorage` (not `localStorage`), meaning it's cleared when the browser tab closes. This keeps admin sessions short-lived and separate from the user token.

---

## 3. Email Notifications

### SMTP Configuration

Emails are sent via `aiosmtplib` using STARTTLS on port 587. Configuration:

| Env Var | Purpose |
|---|---|
| `SMTP_HOST` | SMTP server hostname (e.g. `mail.infomaniak.com`) |
| `SMTP_PORT` | SMTP port (default: 587) |
| `SMTP_USER` | SMTP username (typically the full email address) |
| `SMTP_PASSWORD` | SMTP password or app-specific password |
| `SMTP_FROM` | Sender address (e.g. `support@boblabs.eu`) |
| `SMTP_TLS` | Use STARTTLS (default: true) |

### Email Events

1. **Trial request submitted** → Email sent to `ADMIN_EMAIL` with request details and link to `/admin`
2. **Token generated** → If `send_email` is checked and user email is set, the token is emailed to the user with login instructions

### Error Handling

Email sending is fire-and-forget: if SMTP fails, the API request still succeeds and the error is logged. The admin can always copy the token manually from the admin panel.

---

## 4. User Workflow (End-to-End)

### For a New User

1. Visit landing page at `/` (or `/fr` for French)
2. Click "Request trial access" → fill form at `/request-trial`
3. Admin receives email notification → reviews at `/admin`
4. Admin clicks "Generate Token" → sets expiry → token auto-emailed to user
5. User receives token → goes to `/login` → pastes token
6. JWT issued → stored in `localStorage` → auto-attached to all API requests
7. User accesses all platform features until token expires

### For the Admin

1. Go to `/admin` → enter `ADMIN_SECRET` password
2. Review trial requests in the "Trial Requests" tab
3. Approve (generate token) or reject requests
4. Manage active tokens in the "Access Tokens" tab
5. Revoke tokens to immediately cut access
6. Create standalone tokens (not tied to trial requests) for direct invitations

---

## 5. Technical Implementation Details

### Backend Files

| File | Purpose |
|---|---|
| `control-plane/app/models/access_token.py` | `AccessToken` and `TrialRequest` SQLAlchemy models |
| `control-plane/app/repositories/access_token_repo.py` | CRUD + validation logic for tokens and trial requests |
| `control-plane/app/api/routes/public.py` | Unauthenticated endpoints: trial submit, token validate, admin login |
| `control-plane/app/api/routes/access_tokens.py` | Admin-only endpoints: list/create/revoke tokens, manage trial requests |
| `control-plane/app/services/email_service.py` | Email sending via aiosmtplib (admin notification + token delivery) |
| `control-plane/app/config.py` | Settings class with SMTP, admin, and JWT config |
| `control-plane/app/api/dependencies.py` | JWT creation and validation (`create_access_token`, `get_current_user`) |
| `control-plane/app/migrations/init.sql` | Consolidated schema (includes `access_tokens` and `trial_requests` tables) |

### Frontend Files

| File | Purpose |
|---|---|
| `frontend/src/context/AuthContext.js` | React context: `{token, isAuthenticated, login, logout}` with localStorage |
| `frontend/src/pages/LoginPage.js` | Token entry form → validates → stores JWT |
| `frontend/src/pages/TrialRequestPage.js` | Trial request form (name, email, company, role, purpose) |
| `frontend/src/pages/AdminPage.js` | Admin panel: password login + trial/token management dashboard |
| `frontend/src/services/api.js` | Axios instance with JWT interceptor + all API functions |
| `frontend/src/App.js` | Route protection: `PUBLIC_PATHS` array + auth redirect logic |

### Database Schema

```sql
-- Access tokens (generated by admin, validated by users)
CREATE TABLE access_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token VARCHAR(255) NOT NULL UNIQUE,
    label VARCHAR(255) NOT NULL DEFAULT '',
    email VARCHAR(255) NOT NULL DEFAULT '',
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Trial requests (submitted by visitors)
CREATE TABLE trial_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    enterprise VARCHAR(255) NOT NULL DEFAULT '',
    role VARCHAR(255) NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

---

## 6. Configuration Reference

All variables go in `.env` at the project root:

```env
# Admin panel password (required for /admin access)
ADMIN_SECRET=your-strong-admin-password

# Email address where trial request notifications are sent
ADMIN_EMAIL=support@boblabs.eu

# Public URL of the platform (used in email links)
APP_BASE_URL=https://boblabs.eu

# SMTP configuration for sending emails
SMTP_HOST=mail.infomaniak.com
SMTP_PORT=587
SMTP_USER=support@boblabs.eu
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=support@boblabs.eu
SMTP_TLS=true

# Contact email shown on landing page (baked into React build)
REACT_APP_CONTACT_EMAIL=support@boblabs.eu
```

---

## 7. Authorization & RBAC — Architecture Plan

> **Status: ✅ Partially Implemented** — The JSONB ACL model (`acl` column) and the `authorization.py` service are implemented. Labs, projects, resources, conversations, and wallets use ACL-based filtering. Sections 7-8 below document the full design; items marked ⏳ are planned but not yet built.

### Problem Statement

Currently, all authenticated users see all data (labs, projects, resources, RAG collections, wallets). There is no concept of data ownership or per-user visibility. The platform needs:

1. **Per-resource ownership** — Labs, projects, resources, RAG collections, and web3 wallets should have an owner
2. **Granular permissions** — Owner can grant roles: modify access, read-only access
3. **Section-level gating** — Servers, workflows, commands, terminal, and logs should be admin-whitelisted only
4. **Shared modules** — Metrics remain globally visible; the authorization module must be reusable across all data modules

### Design Principles

- **Single authorization module** — One reusable service for all permission checks
- **JSON-based ACL** — Permissions stored as a JSONB column on each resource, no additional join tables
- **Backend enforcement** — All filtering happens in SQL queries, never client-side only
- **Frontend gating** — UI hides unauthorized content and shows appropriate messages
- **Backward compatible** — Resources with no ACL default to admin-owned (migration sets owner from existing data)

### Permission Model

Each resource that supports ownership gets a JSONB column `acl` (Access Control List):

```json
{
  "owner": "alice@company.com",
  "editors": ["bob@company.com", "carol@company.com"],
  "viewers": []
}
```

**Role Hierarchy:**

| Role | Can View | Can Edit | Can Delete | Can Manage ACL |
|---|---|---|---|---|
| `owner` | ✅ | ✅ | ✅ | ✅ |
| `editor` | ✅ | ✅ | ❌ | ❌ |
| `viewer` | ✅ | ❌ | ❌ | ❌ |
| `admin` (JWT role) | ✅ | ✅ | ✅ | ✅ |
| No match | ❌ | ❌ | ❌ | ❌ |

**Rules:**
- `owner` is a single email string (the user who created the resource)
- `editors` is an array of emails with read+write access
- `viewers` is an array of emails with read-only access
- Empty arrays = no extra grants (owner-only by default)
- JWT `role: admin` bypasses all ACL checks (sees everything)
- JWT `sub` field is the user's email, used for matching

### Section Whitelisting

For infrastructure-sensitive sections (servers, workflows, commands, terminal, logs), a platform-level whitelist controls access:

```json
// Stored in a new platform_settings table or as env var
{
  "infra_access": ["admin@boblabs.eu", "devops@boblabs.eu"]
}
```

Users not in `infra_access` see a friendly message:
> "Curious? Deploy Bob Labs on your own infrastructure to explore server management, workflows, and more."

This keeps the trial/demo experience clean while protecting infrastructure controls.

---

## 8. RBAC Implementation Plan

> **Implementation Status:**
> - ✅ Phase 1 — Authorization service (`services/authorization.py`) — **Implemented**
> - ✅ Phase 2 — ACL columns on core tables — **Implemented** (labs, projects, resources, conversations, wallets)
> - ✅ Phase 3 — Model updates — **Implemented**
> - ✅ Phase 4 — Repository filtering — **Implemented**
> - ✅ Phase 5 — Route-level permission checks — **Implemented**
> - ⏳ Phase 6 — Frontend integration (Share modal, permission hooks) — **Partial**
> - ⏳ Phase 7 — Admin panel extensions (infra whitelist) — **Planned**

### Phase 1 — Authorization Service (Backend Core)

**New file: `control-plane/app/services/authorization.py`**

A single, importable module used by all routes:

```python
# Pseudo-code structure

ACL_SCHEMA = {
    "owner": str,         # email
    "editors": list[str], # emails
    "viewers": list[str], # emails
}

class Permission(Enum):
    VIEW = "view"
    EDIT = "edit"
    DELETE = "delete"
    MANAGE = "manage"

def check_permission(user: dict, acl: dict, permission: Permission) -> bool:
    """Check if a user has a specific permission on a resource."""
    # admin role bypasses everything
    # owner has all permissions
    # editors have VIEW + EDIT
    # viewers have VIEW only
    # no match = denied

def filter_query_by_access(query, model, user: dict):
    """Add WHERE clause to filter resources the user can see."""
    # admin: no filter
    # others: WHERE acl->>'owner' = email
    #            OR acl->'editors' ? email
    #            OR acl->'viewers' ? email

def require_permission(permission: Permission):
    """FastAPI dependency that loads resource + checks permission."""
    # Returns a Depends() that can be injected into any route

def get_default_acl(user_email: str) -> dict:
    """Return default ACL for a newly created resource."""
    return {"owner": user_email, "editors": [], "viewers": []}
```

**Key design:** The `filter_query_by_access()` function uses PostgreSQL JSONB operators (`->>', `?`, `@>`) to filter at the SQL level. No Python-side filtering — everything is database-efficient.

### Phase 2 — Database Migration

**New migration: `016_add_acl_columns.sql`**

```sql
-- Add ACL column to all owned resources
ALTER TABLE labs ADD COLUMN acl JSONB NOT NULL DEFAULT '{"owner":"admin","editors":[],"viewers":[]}';
ALTER TABLE projects ADD COLUMN acl JSONB NOT NULL DEFAULT '{"owner":"admin","editors":[],"viewers":[]}';
ALTER TABLE resources ADD COLUMN acl JSONB NOT NULL DEFAULT '{"owner":"admin","editors":[],"viewers":[]}';
ALTER TABLE rag_collections ADD COLUMN acl JSONB NOT NULL DEFAULT '{"owner":"admin","editors":[],"viewers":[]}';
ALTER TABLE wallets ADD COLUMN acl JSONB NOT NULL DEFAULT '{"owner":"admin","editors":[],"viewers":[]}';

-- GIN index for fast JSONB containment queries
CREATE INDEX idx_labs_acl ON labs USING GIN (acl);
CREATE INDEX idx_projects_acl ON projects USING GIN (acl);
CREATE INDEX idx_resources_acl ON resources USING GIN (acl);
CREATE INDEX idx_rag_collections_acl ON rag_collections USING GIN (acl);
CREATE INDEX idx_wallets_acl ON wallets USING GIN (acl);

-- Platform settings for infra whitelisting
CREATE TABLE IF NOT EXISTS platform_settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

INSERT INTO platform_settings (key, value) VALUES
    ('infra_access', '{"emails": []}')
ON CONFLICT (key) DO NOTHING;
```

### Phase 3 — Model Updates

Add `acl` column to each SQLAlchemy model:

```python
# In each model (Lab, Project, Resource, RagCollection, Wallet)
from sqlalchemy.dialects.postgresql import JSONB

acl = Column(JSONB, nullable=False, server_default='{"owner":"admin","editors":[],"viewers":[]}')
```

Add a new `PlatformSettings` model for infra_access and future platform-level config.

### Phase 4 — Repository Updates

Each repository's list/get methods gain a `user` parameter:

```python
# Example: LabRepository

async def get_all(self, user: dict | None = None) -> list[Lab]:
    query = select(Lab).order_by(Lab.name)
    if user and user.get("role") != "admin":
        email = user.get("sub", "")
        query = query.where(
            or_(
                Lab.acl["owner"].astext == email,
                Lab.acl["editors"].contains(f'["{email}"]'),
                Lab.acl["viewers"].contains(f'["{email}"]'),
            )
        )
    return (await self.db.execute(query)).scalars().all()
```

Create methods auto-set `acl.owner` to the current user's email.
Update/delete methods check edit/delete permissions before proceeding.

### Phase 5 — Route Updates

Each route handler injects the authorization check:

```python
@router.get("")
async def list_labs(db: DbSession, user: dict = Depends(get_current_user)):
    repo = LabRepository(db)
    return await repo.get_all(user=user)  # Filtered by ACL

@router.patch("/{lab_id}")
async def update_lab(lab_id: UUID, payload: LabUpdate, db: DbSession, user: dict = Depends(get_current_user)):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    check_permission(user, lab.acl, Permission.EDIT)  # Raises 403 if denied
    return await repo.update(lab_id, **payload.model_dump(exclude_unset=True))
```

For infrastructure sections, a dedicated dependency:

```python
async def require_infra_access(user: dict = Depends(get_current_user), db: DbSession):
    """Check if user is whitelisted for infrastructure sections."""
    if user.get("role") == "admin":
        return user
    settings = await PlatformSettingsRepository(db).get("infra_access")
    if user.get("sub") not in settings.get("emails", []):
        raise HTTPException(status_code=403, detail="infra_restricted")
    return user
```

### Phase 6 — Frontend Integration

**Authorization context:**
- Store user email and role from JWT decode (or from a `/api/v1/me` endpoint)
- Create `usePermission(resource)` hook that checks ACL client-side for UI gating

**Data filtering:**
- No frontend changes needed for data queries — backend returns only authorized resources
- Each list page (labs, projects, resources, etc.) automatically shows only what the user can see

**Infrastructure sections:**
- Servers, workflows, commands, terminal, logs routes check for 403
- On 403 with `detail: "infra_restricted"`, show the friendly message:

```
"Curious? Deploy Bob Labs on your own infrastructure to explore 
server management, workflows, and terminal access."
```

**ACL management UI:**
- Add a "Share" button on lab/project/resource detail pages
- Modal to add/remove editors and viewers by email
- Owner transfer capability

### Phase 7 — Admin Panel Extensions

- Add "Infra Whitelist" tab in `/admin` to manage `infra_access` emails
- Add ability to view all resources across all users (admin bypass)
- Add "Transfer Ownership" action for any resource

### Affected Modules Summary

| Module | ACL Column | Backend Filter | Frontend Gate | Notes |
|---|---|---|---|---|
| Labs | ✅ `acl` JSONB | ✅ filter by owner/editor/viewer | ✅ show only owned/shared | Core module |
| Projects | ✅ `acl` JSONB | ✅ filter by owner/editor/viewer | ✅ show only owned/shared | + resources inherit project ACL |
| Resources | ✅ `acl` JSONB | ✅ filter by owner/editor/viewer | ✅ show only owned/shared | Linked to projects |
| RAG Collections | ✅ `acl` JSONB | ✅ filter by owner/editor/viewer | ✅ show only owned/shared | + per-lab access stays |
| Web3 Wallets | ✅ `acl` JSONB | ✅ filter by owner/editor/viewer | ✅ show only owned/shared | |
| Metrics | ❌ | ❌ | ❌ | Always visible to all authenticated users |
| Servers | ❌ | ✅ via `infra_access` whitelist | ✅ 403 → friendly message | Infrastructure gated |
| Workflows | ❌ | ✅ via `infra_access` whitelist | ✅ 403 → friendly message | Infrastructure gated |
| Commands | ❌ | ✅ via `infra_access` whitelist | ✅ 403 → friendly message | Infrastructure gated |
| Terminal | ❌ | ✅ via `infra_access` whitelist | ✅ 403 → friendly message | Infrastructure gated |
| Logs | ❌ | ✅ via `infra_access` whitelist | ✅ 403 → friendly message | Infrastructure gated |

### File Changes Overview

| Layer | New Files | Modified Files |
|---|---|---|
| Backend | `services/authorization.py`, `models/platform_settings.py`, `repositories/platform_settings_repo.py`, `migrations/init.sql` (ACL columns) | `models/orchestrator.py`, `models/project.py`, `models/resource.py`, `models/rag.py`, `models/wallet.py`, all corresponding repos and route files, `api/dependencies.py` |
| Frontend | `hooks/usePermission.js`, `components/common/InfraRestricted.js`, `components/common/ShareModal.js` | All page components that list/edit resources, `App.js` (infra route handling), `api.js` (new endpoints) |
| Database | `migrations/init.sql` (ACL columns) | — |
| Config | — | `admin` routes (infra whitelist management) |
