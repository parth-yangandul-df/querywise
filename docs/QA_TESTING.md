# QueryWise QA Testing Guide

This guide is for QA engineers testing QueryWise. It covers functionality, test scenarios, and expected behaviors.

---

## 1. What is QueryWise?

QueryWise is a **text-to-SQL application** with a semantic metadata layer. Users ask natural language questions, the system generates SQL using business context, executes against their database, and returns human-readable answers.

**Core Capabilities:**
- Natural language queries → SQL execution
- Semantic layer (glossary terms, metrics, sample queries)
- Multi-database support (PostgreSQL, SQL Server)
- Provider-agnostic LLM (Anthropic, OpenAI, Ollama, OpenRouter, Groq)

---

## 2. Test Environment Setup

### 2.1 Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend runtime |
| Docker | Latest | Container services |
| Docker Compose | Latest | Orchestration |
| Git | Latest | Version control |

### 2.2 API Keys

You need at least one LLM API key for testing:

- **Anthropic**: https://www.anthropic.com
- **OpenAI**: https://platform.openai.com
- **OpenRouter**: https://openrouter.ai
- **Groq**: https://groq.com

> **Note:** Ollama requires no API key (runs locally)

### 2.3 Quick Start

```bash
# 1. Clone the repository
git clone <repo-url> querywise
cd querywise

# 2. Create environment file
cp .env.example .env

# 3. Start services
docker compose up

# 4. Verify services are running
curl http://localhost:8000/api/v1/health     # Should return 200
curl http://localhost:8000/api/v1/ready     # Should return 200
```

### 2.4 Service URLs

| Service | URL | Status Check |
|---------|-----|-------------|
| Frontend (Mantine) | http://localhost:5173 | `/api/v1/health` |
| Angular Chat | http://localhost:4200 | `/api/v1/health` |
| Backend API | http://localhost:8000 | `/api/v1/health` |
| API Docs | http://localhost:8000/docs | Swagger UI |

---

## 3. Test Scenarios

### 3.1 Authentication

| Test ID | Scenario | Expected Result |
|--------|---------|----------------|
| AUTH-01 | Login with valid credentials | Returns JWT cookie, redirects to dashboard |
| AUTH-02 | Login with invalid credentials | Returns 401, error message |
| AUTH-03 | Access protected endpoint without login | Returns 401 Unauthorized |
| AUTH-04 | Logout | Cookie cleared, redirects to login |

**Test Commands:**
```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "test123"}'

# Logout
curl -X POST http://localhost:8000/api/v1/auth/logout
```

### 3.2 Connections

| Test ID | Scenario | Expected Result |
|--------|---------|----------------|
| CONN-01 | Add PostgreSQL connection | Connection created, test successful |
| CONN-02 | Add SQL Server connection | Connection created, test successful |
| CONN-03 | Test invalid connection | Returns connection error message |
| CONN-04 | Introspect connection schema | Tables/columns discovered |
| CONN-05 | Delete connection | Connection removed |

**Test Commands:**
```bash
# Add connection
curl -X POST http://localhost:8000/api/v1/connections \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "TestDB", "connector": "postgresql", "connection_string": "postgresql://user:pass@localhost:5432/testdb"}'

# List connections
curl http://localhost:8000/api/v1/connections \
  -H "Authorization: Bearer <token>"

# Test connection
curl -X POST http://localhost:8000/api/v1/connections/<id>/test \
  -H "Authorization: Bearer <token>"
```

### 3.3 Semantic Layer

| Test ID | Scenario | Expected Result |
|--------|---------|----------------|
| SEM-01 | Add glossary term | Term created with embedding |
| SEM-02 | Add metric definition | Metric created |
| SEM-03 | Add sample query | Sample query saved |
| SEM-04 | Add knowledge document | Document indexed |
| SEM-05 | Search glossary | Returns relevant terms |

**Test Commands:**
```bash
# Add glossary term
curl -X POST http://localhost:8000/api/v1/glossary \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"term": "Revenue", "definition": "Total sales income", "connection_id": "<conn-id>"}'

# List glossary
curl http://localhost:8000/api/v1/glossary \
  -H "Authorization: Bearer <token>"
```

### 3.4 Query Execution (Core Feature)

| Test ID | Scenario | Expected Result |
|--------|---------|----------------|
| QUERY-01 | Simple natural language query | Returns correct SQL + results |
| QUERY-02 | Query with filters | Returns filtered results |
| QUERY-03 | Multi-turn conversation | Maintains context across turns |
| QUERY-04 | Invalid query handling | Returns error message |
| QUERY-05 | Query timeout | Returns timeout error |

**Test Flow:**
1. Create a connection with sample data
2. Introspect the schema
3. Add glossary terms related to the schema
4. Ask a natural language question

**Test Commands:**
```bash
# Execute query
curl -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"question": "Show me all users", "connection_id": "<conn-id>"}'

# Stream query
curl -X POST http://localhost:8000/api/v1/query/stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me all users", "connection_id": "<conn-id>"}'
```

### 3.5 Query History

| Test ID | Scenario | Expected Result |
|--------|---------|----------------|
| HIST-01 | View query history | Returns past queries |
| HIST-02 | Mark query as favorite | Query marked |
| HIST-03 | Retry failed query | Query re-executes |
| HIST-04 | Delete history entry | Entry removed |

**Test Commands:**
```bash
# List history
curl http://localhost:8000/api/v1/query-history \
  -H "Authorization: Bearer <token>"

# Get specific session
curl http://localhost:8000/api/v1/sessions/<session-id> \
  -H "Authorization: Bearer <token>"
```

### 3.6 Health & Monitoring

| Test ID | Scenario | Expected Result |
|--------|---------|----------------|
| HEALTH-01 | Health check endpoint | Returns 200 OK |
| HEALTH-02 | Readiness check | Returns 200 when DB ready |
| HEALTH-03 | Metrics endpoint | Returns Prometheus metrics |
| HEALTH-04 | Rate limiting | Returns 429 after limit |

**Test Commands:**
```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
curl http://localhost:8000/metrics
```

---

## 4. Multi-Turn Conversation Testing

This is critical for QA - testing conversation context.

### Test Scenario: Follow-Up Queries

**Turn 1:**
```
User: Show all employees
Expected: Returns list of employees
```

**Turn 2:**
```
User: Who are developers?
Expected: Filters previous results to developers only
```

**Turn 3:**
```
User: Sort by salary
Expected: Sorts the filtered results
```

### Test Scenario: Context References

**Turn 1:**
```
User: Show Q1 sales
Expected: Returns Q1 data
```

**Turn 2:**
```
User: Add Q2 to this
Expected: Adds Q2 data to Q1 results
```

### Test Scenario: Correction

**Turn 1:**
```
User: Show all orders
Expected: Returns orders
```

**Turn 2:**
```
User: No, I meant customers
Expected: Corrects to customers, doesn't re-query
```

---

## 5. LLM Provider Testing

### 5.1 Provider Configuration

Test each provider by setting in `.env`:

| Provider | Key Variable | Test Focus |
|----------|--------------|------------|
| Anthropic | `DEFAULT_LLM_PROVIDER=anthropic` | Claude quality |
| OpenAI | `DEFAULT_LLM_PROVIDER=openai` | GPT quality |
| Ollama | `DEFAULT_LLM_PROVIDER=ollama` | Local inference |
| OpenRouter | `DEFAULT_LLM_PROVIDER=openrouter` | Multi-model |
| Groq | `DEFAULT_LLM_PROVIDER=groq` | Fast inference |

### 5.2 Embedding Dimension Changes

When switching embedding providers:
- Vector columns are resized
- Existing embeddings are cleared
- Embeddings regenerate in background

Check with:
```bash
curl http://localhost:8000/api/v1/embeddings/status
```

---

## 6. Error Handling Tests

| Test ID | Error Scenario | Expected Behavior |
|--------|---------------|------------------|
| ERR-01 | Invalid SQL syntax | Error message with suggestion |
| ERR-02 | Connection failure | Retry or fallback |
| ERR-03 | LLM timeout | Error message |
| ERR-04 | Rate limit exceeded | 429 with retry-after |

---

## 7. Security Tests

| Test ID | Scenario | Expected Result |
|--------|---------|----------------|
| SEC-01 | SQL injection attempt | Query blocked |
| SEC-02 | DDL attempt | Query blocked |
| SEC-03 | Unauthorized access | 401 returned |
| SEC-04 | XSS in query | Properly escaped |

---

## 8. Performance Benchmarks

| Metric | Target | Test Method |
|--------|--------|-------------|
| Query response time | < 5 seconds | Time curl request |
| Embedding generation | < 2 seconds | Check /embeddings/status |
| Page load time | < 3 seconds | Browser dev tools |
| Concurrent users | 10+ | Load testing |

---

## 9. Test Data

### Sample Questions for Testing

```
1. "Show me all users"
2. "How many orders were placed today?"
3. "What is the total revenue?"
4. "List employees hired last year"
5. "Show top 5 customers by sales"
6. "Which products have low stock?"
```

### Sample Schema for Testing

Create a connection with this test schema:

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100),
    role VARCHAR(50),
    salary NUMERIC
);

INSERT INTO users (name, email, role, salary) VALUES
('John Doe', 'john@test.com', 'Developer', 75000),
('Jane Smith', 'jane@test.com', 'Designer', 65000),
('Bob Wilson', 'bob@test.com', 'Developer', 80000);
```

---

## 10. Known Issues

1. **Multi-turn context**: Follow-up queries may lose context if session expires
2. **Embedding dimension switch**: Requires embeddings regeneration
3. **Ollama latency**: Local inference slower than cloud APIs on CPU

---

## 11. Reporting Bugs

When reporting issues, include:

1. **Steps to reproduce**
2. **Expected behavior**
3. **Actual behavior**
4. **API request/response** (curl or screenshot)
5. **Backend logs** - `docker compose logs backend`
6. **Environment** - `.env` (redact keys)

---

## 12. Useful Commands

```bash
# Check service health
curl http://localhost:8000/api/v1/health

# View backend logs
docker compose logs -f backend

# Check PostgreSQL
docker compose logs app-db

# Restart services
docker compose restart

# View embedding status
curl http://localhost:8000/api/v1/embeddings/status
```