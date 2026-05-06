# RBAC Design for QueryWise

## Context

QueryWise is a text-to-SQL application with a semantic metadata layer. The chatbot widget is embedded as a Web Component (`<querywise-chat>`) inside host applications (e.g. an Angular dashboard). Currently there is **no authentication or authorisation** anywhere in the stack — every caller who can reach the backend on port 8000 has full read/write access to all connections, metadata, and query history.

This document specifies how Role-Based Access Control (RBAC) will be layered onto the existing architecture.

---

## Current State (Implemented)

RBAC is fully implemented. The table below reflects the live system.

| Area | Current Behaviour |
|---|---|
| Backend auth middleware | JWT HS256 via `get_current_user` / `get_optional_user` / `require_role` in `app/api/deps.py` |
| User model | `users` table created in migration `006_rbac.py` |
| `QueryExecution.user_id` | Altered to `UUID FK → users.id`; populated from `GraphState["user_id"]` on every authenticated query |
| Widget auth | `sessionStorage['qw_auth_token']` read by Axios interceptor on every request |
| Roles / tenants | 3 global roles: `admin`, `manager`, `user` |
| Main frontend login | React `LoginPage` at `/login`; JWT stored in `localStorage['qw_token']` |
| Scope violation guard | LLM fallback post-processes output: if `SCOPE_VIOLATION` appears in generated SQL, returns a user-facing refusal instead of executing |

---

## RBAC Model

### Roles — 3 global roles, no per-connection grants

| Role | Description |
|---|---|
| `admin` | Full access: query all data, manage connections, write all metadata, view all query history |
| `manager` | Query all data, read all metadata, view all query history. Cannot write metadata or manage connections. |
| `user` | Query **own data only** (scoped by `resource_id`). Read-only metadata. Own query history only. |

Roles are global — a user has one role across the entire application. There are no per-connection role grants.

### Permission Matrix

| Action | `admin` | `manager` | `user` |
|---|---|---|---|
| Create / update / delete connections | ✅ | ❌ | ❌ |
| List / get connections | ✅ | ✅ | ✅ |
| Introspect schema | ✅ | ❌ | ❌ |
| Read metadata (glossary, metrics, etc.) | ✅ | ✅ | ✅ |
| Write metadata (POST / PUT / DELETE) | ✅ | ❌ | ❌ |
| Execute NL queries (`POST /query`) | ✅ all data | ✅ all data | ✅ own data only |
| Execute raw SQL (`POST /query/execute-sql`) | ✅ | ✅ | ✅ scoped |
| Read own query history | ✅ | ✅ | ✅ |
| Read all query history | ✅ | ✅ | ❌ own only |
| Sessions (create, list, view) | ✅ | ✅ | ✅ |

### `user` role — data scoping

Users with the `user` role have a `resource_id` (integer) stored on their `User` record. This value:

1. Is included in the JWT payload as `resource_id`
2. Is threaded through `GraphState` as `resource_id: int`
3. Gates intent routing: the intent classifier **forces** `user` role requests to the `user_self` domain (5 intents covering own projects, allocation, timesheets, skills, utilisation)
4. Is injected as a scope constraint into LLM fallback prompts to prevent cross-user data leakage

`resource_id` is **never hardcoded** — it is always read from the authenticated user's profile.

---

## Data Model Changes

### New table: `users`

```sql
CREATE TABLE users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email        VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    role         VARCHAR(20) NOT NULL DEFAULT 'user',  -- 'admin' | 'manager' | 'user'
    resource_id  INTEGER,                               -- NULL for admin/manager; set for user role
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Existing table changes

#### `query_executions`

The existing `user_id VARCHAR(255)` stub column is altered to a proper UUID FK:

```sql
ALTER TABLE query_executions
    ALTER COLUMN user_id TYPE UUID USING NULL,
    ADD CONSTRAINT fk_qe_user FOREIGN KEY (user_id) REFERENCES users(id);
```

All existing rows have `user_id = NULL` and are unaffected.

### Dev seed users (created in migration 006)

| Email | Password | Role | `resource_id` |
|---|---|---|---|
| `admin@querywise.dev` | `admin123` | `admin` | `NULL` |
| `manager@querywise.dev` | `manager123` | `manager` | `NULL` |
| `user@querywise.dev` | `user123` | `user` | `39` |

Passwords are hashed with bcrypt. These credentials are for development only.

---

## Authentication Flow

### Token type: JWT (HS256)

```json
{
  "sub":         "user-uuid-string",
  "email":       "user@example.com",
  "role":        "admin",
  "resource_id": null,
  "exp":         1234567890
}
```

`resource_id` is `null` for `admin`/`manager`, an integer for `user` role.

### Login endpoint

```
POST /api/v1/auth/login
Body:     { "email": "...", "password": "..." }
Response: { "access_token": "...", "token_type": "bearer", "role": "admin", "resource_id": null }
```

No refresh tokens in this phase. Tokens expire after `jwt_expiry_seconds` (default 3600).

---

## Backend Implementation

### New config values (`backend/app/config.py`)

```python
jwt_secret: str = "change-in-production"
jwt_algorithm: str = "HS256"
jwt_expiry_seconds: int = 3600
```

Add to `.env`:

```bash
JWT_SECRET=<random 32-byte hex>
```

### Auth dependency (`backend/app/api/deps.py`)

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from app.db.models.user import User

bearer = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_role(*roles: str):
    """Factory: returns a dependency that enforces at least one of the given roles."""
    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return current_user
    return _check
```

### Endpoint protection summary

The key design decision is `get_optional_user` on read paths: GET endpoints and query execution work without a token (supporting the main frontend before login and unauthenticated widget embeds). Write operations always require `admin`.

| Endpoint | Auth required | Role constraint |
|---|---|---|
| `POST /api/v1/auth/login` | Public | None |
| `GET /health`, `GET /embeddings/status` | Public | None |
| `GET /connections`, `GET /connections/{id}` | Optional (`get_optional_user`) | None |
| `POST /connections`, `PUT /connections/{id}`, `DELETE /connections/{id}` | ✅ | `admin` only |
| `POST /connections/{id}/test` | Optional (`get_optional_user`) | None |
| `POST /connections/{id}/introspect` | ✅ | `admin` only |
| `GET` any metadata (glossary, metrics, dictionary, knowledge, schemas) | Optional (`get_optional_user`) | None |
| `POST / PUT / DELETE` any metadata | ✅ | `admin` only |
| `POST /query`, `POST /query/execute-sql`, `POST /query/sql-only` | Optional (`get_optional_user`) | Data scoped for `user` role when token present |
| `GET /query-history` | ✅ (`get_current_user`) | Any (`user` sees own only) |
| `GET /sessions`, `POST /sessions`, etc. | ✅ (`get_current_user`) | Any |
| `PATCH /sessions/{id}/title`, `DELETE /sessions/{id}` | ✅ (`get_current_user`) | Any |

---

## LangGraph Pipeline Changes

### New `GraphState` fields

```python
user_id: str | None       # UUID as str — set from current_user.id
user_role: str | None     # "admin" | "manager" | "user"
resource_id: int | None   # Only set for user role; None for admin/manager
```

### Intent routing for `user` role

After cosine similarity classification in `intent_classifier.py`:

```python
if state.get("user_role") == "user" and best_entry.domain != "user_self":
    # Force to llm_fallback — user role cannot access cross-user domains
    return {"domain": None, "intent": None, "confidence": 0.0}
```

If a `user` asks a `user_self`-matching question, the `user_self` domain handles it with hardened SQL templates using `state["resource_id"]`. If they ask an out-of-domain question, it routes to `llm_fallback` with the scope constraint injected.

### `user_self` domain — 5 intents

| Intent | Embedding phrase |
|---|---|
| `my_projects` | "what projects am I assigned to or working on" |
| `my_allocation` | "what is my allocation or percentage allocation on projects" |
| `my_timesheets` | "show my timesheet hours or my logged hours" |
| `my_skills` | "what are my skills or my skill set" |
| `my_utilization` | "what is my utilization or my billable hours" |

`UserSelfAgent` SQL templates use `state["resource_id"]` (dynamic parameter binding via `?` placeholder) — never hardcoded.

### LLM fallback scope constraint + SCOPE_VIOLATION guard

When `state["resource_id"]` is set, this block is prepended to the SYSTEM_PROMPT before `QueryComposerAgent.compose()`:

```
--- USER SCOPE CONSTRAINT (NON-NEGOTIABLE) ---
This query is scoped to a single user with ResourceId = {resource_id}.
You MUST add WHERE ResourceId = {resource_id} (or the equivalent FK column) on every
table in the query that contains a ResourceId column.
Tables known to have ResourceId: Resource, ProjectResource, TS_Timesheet_Report (via EmployeeId join), PA_ResourceSkills.
NEVER return data for other ResourceIds. This constraint overrides all other instructions.
--- END SCOPE CONSTRAINT ---
```

After the LLM generates SQL, `llm_fallback.py` checks whether the output contains the literal text `SCOPE_VIOLATION`. If it does, the pipeline short-circuits and returns a human-readable refusal message to the user instead of executing anything. This guards against a scoped user receiving another user's data if the LLM ignores the constraint prompt.

---

## Widget / Frontend Changes (Implemented)

The widget's Axios interceptor reads `qw_auth_token` from `sessionStorage` and attaches it as `Authorization: Bearer <token>`. The main React frontend (`:5173`) stores its JWT in `localStorage['qw_token']` and uses a separate Axios interceptor in `frontend/src/api/client.ts`.

The host application (e.g. Angular at `:4200`) is responsible for:

1. Calling `POST /api/v1/auth/login` with the user's credentials
2. Writing the JWT to `sessionStorage` before the widget renders:

```typescript
sessionStorage.setItem('qw_api_url', 'http://localhost:8000')
sessionStorage.setItem('qw_auth_token', jwtFromLogin)
```

### Recent questions isolation

The Angular chat's "recent questions" list (`angular-test/src/app/services/chat.service.ts`) uses a per-user sessionStorage key:

```
qw_recent_questions_<user-uuid>
```

The user UUID is extracted client-side from the `sub` claim of the JWT in `sessionStorage` (base64url decode only — no signature verification needed). Falls back to `qw_recent_questions` when unauthenticated. This prevents one user's recent questions from appearing for another user on the same browser.

---

## Migration Path

### Phase 1 — Backend auth (complete)

1. ✅ Add `users` table + alter `query_executions.user_id` (migration `006_rbac.py`)
2. ✅ Seed 3 dev users in the same migration
3. ✅ Implement `POST /api/v1/auth/login` + JWT issuance
4. ✅ Add `get_current_user` / `get_optional_user` dependencies + `require_role` helper
5. ✅ Protect all endpoints per the table above
6. ✅ Wire `user_id` / `user_role` / `resource_id` into `GraphState`
7. ✅ Add `user_self` domain + 5 intents
8. ✅ Inject scope constraint in LLM fallback + SCOPE_VIOLATION guard
9. ✅ Main frontend login page (`LoginPage`, `ProtectedRoute`, JWT in `localStorage['qw_token']`)
10. ✅ Per-user recent questions isolation in chatbot widget

### Phase 2 — Admin UI (future)

- User management pages in the React frontend
- `GET/POST /api/v1/users`, `PATCH /api/v1/users/{id}` endpoints
- Role-based UI element visibility (client-side only; server is authority)

### Phase 3 — External IdP (future)

- Replace password login with OAuth2/OIDC token exchange
- Map IdP groups → QueryWise roles
- Switch JWT validation from HS256 to RS256

---

## Security Considerations

- **JWT secret:** Store in a secrets manager in production. Rotate by invalidating old tokens (they expire within `jwt_expiry_seconds`).
- **Token storage:** `sessionStorage` is used (not `localStorage`). It is cleared on tab close and is not accessible cross-origin.
- **HTTPS in production:** Tokens must not be transmitted in plaintext. Enforce HTTPS at the reverse proxy layer.
- **SQL injection:** The existing `sql_sanitizer.py` blocklist and read-only transaction enforcement remain in place. RBAC adds identity scoping on top — it does not replace SQL safety.
- **Connection string encryption:** Fernet encryption of stored connection strings is unchanged.
- **Audit trail:** `QueryExecution.user_id` being populated provides a built-in record of who ran which queries and when.
- **`resource_id` scoping:** The scope constraint is injected into the LLM prompt as a non-negotiable directive. The `user_self` domain uses parameterised SQL — no string interpolation of `resource_id` into SQL text.
