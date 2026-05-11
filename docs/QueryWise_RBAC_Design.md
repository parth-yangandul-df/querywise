# QueryWise — Role-Based Access Control Design Document

**Version:** 1.0
**Date:** May 2026
**Stack:** Angular 21 (UI) · FastAPI / Python (Backend) · PostgreSQL (App DB) · Azure SQL (Target DB)
**Status:** Draft — Internal

---

## 1. Overview

QueryWise is an AI-powered natural language query interface that translates user prompts into SQL queries against a target Azure SQL database. Because QueryWise allows users to ask arbitrary questions in plain English, a robust Role-Based Access Control (RBAC) system is critical: it determines what data each user may see and what administrative actions they may perform.

This document defines:

- The three QueryWise roles and their permissions
- The PostgreSQL schema for storing RBAC data (app database)
- The enforcement layer design inside FastAPI
- Row-level filtering rules for the User role
- Middleware and dependency-injection patterns

---

## 2. Role Definitions

### 2.1 Admin

> **Full unrestricted access. Admin can do everything.**

Admins are system super-users. They have no data-visibility restrictions and can perform all platform management functions.

**Admin capabilities:**
- Query any table in the target Azure SQL database, with no row-level filter applied
- Manage users: create, edit, deactivate, delete accounts
- Manage roles: assign or revoke roles; define new role entries
- Maintain metadata: configure table/column mappings, data source connections, field aliases
- View all audit and query logs across all users

---

### 2.2 Manager

> **Query anything. Manage nothing.**

Managers have the same data-query breadth as Admins — they can see all records across all tables — but they have zero platform-management permissions. They cannot touch user accounts, role definitions, or metadata configuration.

**Manager capabilities:**
- Query any table in the target Azure SQL database, with no row-level filter applied
- View results across all employees, clients, projects, timesheets, and financials
- View own activity/audit logs

**Manager restrictions (cannot):**
- Create, edit, or delete user accounts
- Assign or revoke roles
- Modify or maintain metadata / schema mappings
- Configure data source connections
- View other users' audit logs

---

### 2.3 User

> **Own data only. No cross-resource or sensitive table access.**

Users are individual contributors or employees. All queries issued on their behalf are automatically constrained to rows where the `resource_id` (or `employee_id`) matches their identity. They cannot access data belonging to other employees, client records, or any platform-management function.

**User capabilities:**
- Query own project assignments
- Query own resource allocations
- Query own timesheet entries (filtered by `resource_id` / `employee_id`)
- Query any other table to which they are scoped — as long as the query is filtered to their own identity
- View own activity logs

**User restrictions (cannot):**
- Query client data (zero access regardless of filter)
- Query other employees' timesheets, allocations, or project data
- Access any financial or billing records
- Perform any user, role, or metadata management

---

## 3. Permission Matrix

`✓` = permitted · `✗` = denied · `Own Only` = permitted but row-filtered to the caller's `resource_id`

| Category | Action / Capability | Admin | Manager | User |
|---|---|:---:|:---:|:---:|
| Data Querying | Query any table (all records) | ✓ | ✓ | ✗ |
| Data Querying | Query own project data | ✓ | ✓ | ✓ |
| Data Querying | Query own allocation data | ✓ | ✓ | ✓ |
| Data Querying | Query own timesheet (by resource ID) | ✓ | ✓ | ✓ |
| Data Querying | Query other users' timesheets | ✓ | ✓ | ✗ |
| Data Querying | Query client data | ✓ | ✓ | ✗ |
| Data Querying | Query financial / billing data | ✓ | ✓ | ✗ |
| User Mgmt | Create users | ✓ | ✗ | ✗ |
| User Mgmt | Edit users | ✓ | ✗ | ✗ |
| User Mgmt | Delete users | ✓ | ✗ | ✗ |
| User Mgmt | View user list | ✓ | ✗ | ✗ |
| Role Mgmt | Assign / revoke roles | ✓ | ✗ | ✗ |
| Role Mgmt | Create / edit role definitions | ✓ | ✗ | ✗ |
| Metadata Mgmt | Maintain metadata tables | ✓ | ✗ | ✗ |
| Metadata Mgmt | Edit schema / field mappings | ✓ | ✗ | ✗ |
| Metadata Mgmt | Configure data source connections | ✓ | ✗ | ✗ |
| Audit | View all audit logs | ✓ | ✗ | ✗ |
| Audit | View own activity logs | ✓ | ✓ | ✓ |

---

## 4. PostgreSQL App Database Schema

All RBAC data lives in the QueryWise PostgreSQL application database (not the target Azure SQL database).

### 4.1 `users`

Stores authenticated user accounts and their bound resource identity.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | Surrogate primary key |
| `email` | VARCHAR(255) | NOT NULL, UNIQUE | Login email / identity |
| `full_name` | VARCHAR(255) | NOT NULL | Display name |
| `password_hash` | VARCHAR(255) | NOT NULL | Bcrypt hash |
| `resource_id` | VARCHAR(100) | NULLABLE, UNIQUE | Employee / resource ID in target DB |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | Soft-delete / deactivation flag |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Account creation timestamp |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Last modified timestamp |

---

### 4.2 `roles`

Lookup table for role definitions. Seeded with three records: `admin`, `manager`, `user`.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | SMALLINT | PK | Role identifier |
| `name` | VARCHAR(50) | NOT NULL, UNIQUE | Role slug: admin \| manager \| user |
| `label` | VARCHAR(100) | NOT NULL | Human-readable label |
| `description` | TEXT | NULLABLE | Role description |

**Seed data:**

```sql
INSERT INTO roles (id, name, label, description) VALUES
  (1, 'admin',   'Administrator', 'Full access: query + manage users, roles, metadata'),
  (2, 'manager', 'Manager',       'Query all data; no management permissions'),
  (3, 'user',    'User',          'Query own data only, filtered by resource_id');
```

---

### 4.3 `user_roles`

Junction table assigning one or more roles to a user. In QueryWise's current model each user has exactly one role, but the many-to-many structure allows future role composition.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `user_id` | UUID | FK → users.id, ON DELETE CASCADE | User reference |
| `role_id` | SMALLINT | FK → roles.id, ON DELETE RESTRICT | Role reference |
| `assigned_by` | UUID | FK → users.id, NULLABLE | Admin who made the assignment |
| `assigned_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Assignment timestamp |

Primary key: `(user_id, role_id)`

---

### 4.4 `table_access_policy`

Defines which roles may query each logical table in the target Azure SQL database, and whether row-level filtering must be applied.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | SERIAL | PK | Surrogate key |
| `table_name` | VARCHAR(200) | NOT NULL | Target table name (Azure SQL) |
| `role_id` | SMALLINT | FK → roles.id | Role this policy applies to |
| `can_query` | BOOLEAN | NOT NULL, DEFAULT FALSE | Whether the role may query this table |
| `row_filter_col` | VARCHAR(100) | NULLABLE | Column used for row-level filter (e.g. resource_id) |
| `filter_source` | VARCHAR(50) | NULLABLE | JWT claim to match: resource_id \| user_id |

**Example seed rows:**

```sql
-- timesheets: manager sees all, user sees only own rows
INSERT INTO table_access_policy
  (table_name, role_id, can_query, row_filter_col, filter_source)
VALUES
  ('timesheets', 2, TRUE,  NULL,          NULL),
  ('timesheets', 3, TRUE,  'resource_id', 'resource_id'),

-- clients: admin + manager only
  ('clients',    1, TRUE,  NULL,  NULL),
  ('clients',    2, TRUE,  NULL,  NULL),
  ('clients',    3, FALSE, NULL,  NULL);
```

---

### 4.5 `audit_log`

Records every query attempt for compliance and debugging.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | BIGSERIAL | PK | Surrogate key |
| `user_id` | UUID | FK → users.id | Who made the request |
| `role_name` | VARCHAR(50) | NOT NULL | Role active at query time |
| `endpoint` | VARCHAR(255) | NOT NULL | API path called |
| `nl_query` | TEXT | NULLABLE | Natural language input (chatbot) |
| `sql_generated` | TEXT | NULLABLE | SQL generated (redacted if sensitive) |
| `status` | VARCHAR(20) | NOT NULL | allowed \| denied \| error |
| `denied_reason` | TEXT | NULLABLE | Populated when status = denied |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Request timestamp |

---

### 4.6 Full DDL — PostgreSQL

```sql
-- Enable UUID support
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE roles (
  id          SMALLINT      PRIMARY KEY,
  name        VARCHAR(50)   NOT NULL UNIQUE,
  label       VARCHAR(100)  NOT NULL,
  description TEXT
);

CREATE TABLE users (
  id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  email         VARCHAR(255)  NOT NULL UNIQUE,
  full_name     VARCHAR(255)  NOT NULL,
  password_hash VARCHAR(255)  NOT NULL,
  resource_id   VARCHAR(100)  UNIQUE,
  is_active     BOOLEAN       NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE user_roles (
  user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id     SMALLINT    NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
  assigned_by UUID        REFERENCES users(id),
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE table_access_policy (
  id             SERIAL        PRIMARY KEY,
  table_name     VARCHAR(200)  NOT NULL,
  role_id        SMALLINT      NOT NULL REFERENCES roles(id),
  can_query      BOOLEAN       NOT NULL DEFAULT FALSE,
  row_filter_col VARCHAR(100),
  filter_source  VARCHAR(50),
  UNIQUE (table_name, role_id)
);

CREATE TABLE audit_log (
  id            BIGSERIAL     PRIMARY KEY,
  user_id       UUID          NOT NULL REFERENCES users(id),
  role_name     VARCHAR(50)   NOT NULL,
  endpoint      VARCHAR(255)  NOT NULL,
  nl_query      TEXT,
  sql_generated TEXT,
  status        VARCHAR(20)   NOT NULL,
  denied_reason TEXT,
  created_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);
```

---

## 5. FastAPI Enforcement Architecture

### 5.1 JWT Token Payload

The JWT issued on login must embed the user's role and `resource_id` so enforcement doesn't require a database round-trip on every request.

```json
{
  "sub":         "user-uuid-here",
  "email":       "alice@company.com",
  "role":        "user",
  "resource_id": "EMP-00123",
  "exp":         1748000000
}
```

---

### 5.2 Dependency Injection — Role Guards

```python
# rbac/dependencies.py
from fastapi import Depends, HTTPException, status
from .jwt import decode_token   # returns TokenPayload dataclass

def get_current_user(token=Depends(oauth2_scheme)) -> TokenPayload:
    return decode_token(token)

def require_admin(user=Depends(get_current_user)) -> TokenPayload:
    if user.role != 'admin':
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Admin access required')
    return user

def require_manager_or_above(user=Depends(get_current_user)) -> TokenPayload:
    if user.role not in ('admin', 'manager'):
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Manager access required')
    return user

def require_any_role(user=Depends(get_current_user)) -> TokenPayload:
    # Authenticated users of all roles allowed
    return user
```

---

### 5.3 Route Protection Examples

```python
# routes/admin.py  —  Admin-only endpoints
@router.post('/users',          dependencies=[Depends(require_admin)])
@router.delete('/users/{id}',   dependencies=[Depends(require_admin)])
@router.put('/roles/assign',    dependencies=[Depends(require_admin)])
@router.put('/metadata',        dependencies=[Depends(require_admin)])

# routes/query.py  —  Query endpoint (all roles, but filtered)
@router.post('/query')
async def run_query(body: QueryRequest, user=Depends(require_any_role)):
    policy = await get_policy(body.target_table, user.role)
    if not policy.can_query:
        raise HTTPException(403, f'Role {user.role} cannot query {body.target_table}')
    sql = generate_sql(body.nl_prompt, policy, user)
    return await execute_on_azure(sql)
```

---

### 5.4 Row-Level Filter Injection

When `table_access_policy` defines a `row_filter_col`, the SQL generator appends a WHERE clause automatically before sending the query to Azure SQL:

```python
# sql_generator.py
def apply_row_filter(sql: str, policy: TablePolicy, user: TokenPayload) -> str:
    if not policy.row_filter_col:
        return sql   # admin / manager — no filter
    filter_value = getattr(user, policy.filter_source)  # e.g. user.resource_id
    if not filter_value:
        raise HTTPException(403, 'User has no resource_id; cannot filter')
    # Inject WHERE clause safely (parameterised in final execution)
    return f'{sql} WHERE {policy.row_filter_col} = :__rbac_filter'

# In execution layer, bind the parameter:
params['__rbac_filter'] = user.resource_id
```

---

### 5.5 Request Flow

Every query request passes through this pipeline:

```
1.  Angular / Chatbot  →  POST /query  (Bearer JWT)
2.  FastAPI JWT middleware  →  decode token, extract role + resource_id
3.  require_any_role()  →  user authenticated?
4.  table_access_policy lookup  →  can this role query this table?
5.  NL → SQL generation (LLM call)
6.  apply_row_filter()  →  inject WHERE clause if role = user
7.  Execute on Azure SQL (parameterised)
8.  audit_log.insert()  →  log status (allowed / denied)
9.  Return results to client
```

---

## 6. UI Behaviour by Role

> Note: UI hiding is a UX convenience, not a security control. All enforcement is server-side.

| UI Area | Admin | Manager | User |
|---|---|---|---|
| User Management menu | Visible | Hidden | Hidden |
| Role Management menu | Visible | Hidden | Hidden |
| Metadata Config menu | Visible | Hidden | Hidden |
| Audit Logs (all users) | Visible | Hidden | Hidden |
| My Activity Log | Visible | Visible | Visible |
| Query scope indicator | All data | All data | My data only |
| Chatbot table selector | All tables | All tables | Own-data tables only |

---

## 7. Security Considerations

| Risk | Mitigation |
|---|---|
| JWT role tampering | Sign JWTs with RS256; verify signature on every request in FastAPI middleware |
| SQL injection via NL query | All Azure SQL execution uses parameterised queries; `__rbac_filter` bound as param, never string-concatenated |
| Role escalation | `role` field in JWT is set only at login from DB; users cannot self-assign roles via API |
| Resource_id spoofing | `resource_id` injected from server-side JWT claim, never accepted from request body for filter purposes |
| Missing policy row = deny | `table_access_policy` lookup returns `can_query=FALSE` by default; missing entry = denied |
| Audit log bypass | `audit_log.insert()` runs in a `finally` block so denied requests are still logged |
| Token expiry | Short-lived access tokens (15 min) + refresh token rotation; refresh tokens stored in HttpOnly cookie |

---

## 8. Implementation Checklist

### Phase 1 — Schema & Seed
- [ ] Run PostgreSQL DDL (Section 4.6)
- [ ] Seed `roles` table with 3 records
- [ ] Seed `table_access_policy` for all target Azure SQL tables
- [ ] Add `resource_id` to existing user records

### Phase 2 — FastAPI Enforcement
- [ ] Implement JWT decode middleware with `role` + `resource_id` claims
- [ ] Create `require_admin`, `require_manager_or_above`, `require_any_role` dependencies
- [ ] Add dependencies to all existing route handlers
- [ ] Implement `table_access_policy` lookup in query pipeline
- [ ] Implement `apply_row_filter` in SQL generation layer

### Phase 3 — Audit & Testing
- [ ] Implement `audit_log` insert in query handler (`finally` block)
- [ ] Write pytest tests: each role × each table × allowed / denied scenarios
- [ ] Penetration test: attempt role escalation via modified JWT
- [ ] Verify row-filter injection cannot be bypassed via NL prompt manipulation

### Phase 4 — Angular UI
- [ ] Decode JWT role in Angular auth service
- [ ] Use `*ngIf` directives to hide admin/manager menus from lower roles
- [ ] Display query-scope indicator in chatbot header (`Showing: Your data only`)
- [ ] Restrict chatbot table picker to policy-allowed tables per role

---

### Future: Microsoft Azure AD Integration

**What changes when you switch to Microsoft login:**
- Auth middleware — swap custom JWT for Azure AD token validation (`fastapi-azure-auth`)
- Login flow — add a post-login Microsoft Graph API call to fetch and store `employee_id` / `resource_id`
- Angular UI — replace login form with Microsoft login button (MSAL library)

**What stays the same:**
- PostgreSQL schema — zero changes
- FastAPI role guards — same `require_admin`, `require_manager_or_above` dependencies
- Row-level filter logic — same `apply_row_filter()` function
- `table_access_policy` — no changes
- Audit logging — no changes

The `resource_id` column in the `users` table is exactly where the Microsoft Graph employee ID lands — no schema migration required.

---

*Document prepared for QueryWise internal engineering use. Review with the security team before production deployment.*
