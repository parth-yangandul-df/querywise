# QueryWise Onboarding Guide

Welcome to QueryWise! This guide will walk you through setting up QueryWise locally for development.

## What is QueryWise

QueryWise is a text-to-SQL application with a semantic metadata layer. Users ask natural language questions, an LLM generates SQL using business context (glossary terms, metrics, sample queries), executes against their database, and returns human-readable answers.

### Key Features

- **Natural language to SQL**: Ask questions in plain English, get SQL results
- **Semantic layer**: Glossary terms, metrics, and sample queries provide business context
- **Multi-database support**: Connect to PostgreSQL and SQL Server databases
- **Provider-agnostic LLM**: Works with Anthropic, OpenAI, Ollama, OpenRouter, or Groq

---

## Prerequisites

Before starting, ensure you have the following installed:

| Requirement | Minimum Version | Notes |
|--------------|-----------------|-------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend runtime |
| Docker | Latest | Database and optional services |
| Docker Compose | Latest | Orchestration |
| Git | Latest | Version control |

### Required API Keys

Depending on your chosen LLM provider, you'll need at least one API key:

- **Anthropic**: Get an API key from [anthropic.com](https://www.anthropic.com)
- **OpenAI**: Get an API key from [platform.openai.com](https://platform.openai.com)
- **OpenRouter**: Get an API key from [openrouter.ai](https://openrouter.ai)
- **Groq**: Get an API key from [groq.com](https://groq.com)

> **Note**: Ollama requires no API key (runs locally)

---

## Quick Start

Follow these steps to get QueryWise running locally.

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-repo/querywise.git
cd querywise
```

### Step 2: Create Environment File

```bash
cp .env.example .env
```

### Step 3: Generate Security Keys

Generate the required encryption key and JWT secret:

```bash
# Generate Fernet encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Generate JWT secret (use a random 32+ character string)
python -c "import secrets; print(secrets.token_hex(32))"
```

Add these to your `.env` file:

```env
ENCRYPTION_KEY=<your-generated-fernet-key>
JWT_SECRET=<your-generated-jwt-secret>
```

### Step 4: Start PostgreSQL

Start only the PostgreSQL container (the metadata database with pgvector):

```bash
docker compose up app-db -d
```

Wait for PostgreSQL to be ready (usually 5-10 seconds).

### Step 5: Set Up Backend

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

# Install dependencies
pip install -e ".[llm,dev]"

# Run database migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload
```

The backend will start at `http://localhost:8000`.

### Step 6: Set Up Frontend

In a new terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend will start at `http://localhost:5173`.

### Step 7: Set Up Chatbot Frontend

In another new terminal:

```bash
cd angular-test
npm install
npm run start
```

The Angular chat will start at `http://localhost:4200`.

---

## Service URLs

After starting all services, access QueryWise at:

| Service | URL | Description |
|---------|-----|------------|
| Frontend (Mantine) | http://localhost:5173 | Main admin UI |
| Angular Chat | http://localhost:4200 | Chat interface |
| Backend API | http://localhost:8000 | REST API |
| API Docs | http://localhost:8000/docs | OpenAPI documentation |
| Health Check | http://localhost:8000/api/v1/health | Liveness probe |
| Readiness Check | http://localhost:8000/api/v1/ready | Readiness probe |
| Prometheus Metrics | http://localhost:8000/metrics | Metrics endpoint |

---

## LLM Providers

QueryWise supports multiple LLM providers. Configure your chosen provider in the `.env` file.

### Anthropic

```bash
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=<your-anthropic-key>
OPENAI_API_KEY=<your-openai-key>  # Required for embeddings
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

### OpenAI

```bash
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-5.2
OPENAI_API_KEY=<your-openai-key>
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

### Ollama (Local)

Ollama runs locally and requires no API keys. Two deployment options:

**Option A: Native Ollama on macOS (Recommended - GPU-accelerated)**

```bash
# Install and start Ollama
brew install ollama
ollama serve

# Pull required models
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

```bash
# .env configuration
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_BASE_URL=http://host.docker.internal:11434
EMBEDDING_DIMENSION=768
```

**Option B: Ollama in Docker (CPU-only)**

```bash
# Start with Docker profile
docker compose --profile ollama-docker up
```

```bash
# .env configuration
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_BASE_URL=http://ollama:11434
EMBEDDING_DIMENSION=768
```

### OpenRouter

```bash
DEFAULT_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=<your-openrouter-key>
OPENROUTER_MODEL=deepseek/deepseek-v3.2          # Composer (SQL generation + error correction)
RESOLVER_MODEL=openai/gpt-4.1-nano               # Resolver (intent classification + question rewrite)
INTERPRETER_MODEL=meta-llama/llama-3.1-8b-instruct # Interpreter (result → natural language summary)
EMBEDDING_PROVIDER=openrouter                     # Route embeddings through OpenRouter
EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

### Groq

```bash
DEFAULT_LLM_PROVIDER=groq
GROQ_API_KEY=<your-groq-key>
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

**Groq Extractor Mode** (faster intent classification):

```bash
USE_GROQ_EXTRACTOR=true
```

---

## New Features

QueryWise includes several production-ready features:

### Authentication

QueryWise uses HttpOnly cookies for authentication with CSRF protection:

- JWT tokens stored in secure HttpOnly cookies
- CSRF tokens required for state-changing operations
- Rate limiting on login endpoint (5 requests per minute)

### Rate Limiting

The application implements rate limiting to prevent abuse:

| Endpoint | Limit |
|----------|-------|
| `/auth/login` | 5 requests/minute |
| General API | 30 requests/minute (configurable) |

Rate limit headers are included in responses:

```http
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 29
X-RateLimit-Reset: 1715000000
```

### Health Checks

Two endpoints for container orchestration:

- **`/api/v1/health`**: Liveness probe - returns 200 if the application is running
- **`/api/v1/ready`**: Readiness probe - returns 200 if the application can handle requests (DB connected)

```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
```

### Prometheus Metrics

Prometheus metrics are exposed at `/metrics` (unauthenticated):

```bash
curl http://localhost:8000/metrics
```

Metrics include:

- Request duration histograms
- Request counts by endpoint
- LLM provider metrics
- Database connection metrics

### Backup and Restore

Automated backup scripts are provided:

```bash
# Create a backup
cd backend
./scripts/backup.sh

# Restore from a backup
cd backend
./scripts/restore.sh backups/querywise_20260427_120000.sql.gz
```

Backups are stored in `backend/backups/` with 30 backups retained.

### Key Rotation

Rotate the encryption key without losing data:

```bash
curl -X POST http://localhost:8000/api/v1/admin/rotate-encryption-key \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"new_key": "<new-fernet-key>"}'
```

This re-encrypts all stored connection strings with the new key.

---

## Security Checklist for Production

Before deploying to production, ensure:

### Environment Variables

- [ ] Set `ENCRYPTION_KEY` to a secure Fernet key (not the example key)
- [ ] Set `JWT_SECRET` to a random 32+ character string
- [ ] Set `ENVIRONMENT=production`
- [ ] Set `DEBUG=false`

### Authentication

- [ ] Configure proper `CORS_ORIGINS` (restrict to your domain)
- [ ] Use HTTPS (TLS/SSL)
- [ ] Set secure cookie settings (HttpOnly, Secure, SameSite)

### Rate Limiting

- [ ] Review and adjust rate limits as needed
- [ ] Monitor rate limit metrics in Prometheus

### Database

- [ ] Use strong passwords for database connections
- [ ] Enable SSL connections to external databases
- [ ] Configure regular backups

### LLM Provider

- [ ] Monitor API usage and costs
- [ ] Set up usage alerts

### Monitoring

- [ ] Configure Prometheus scraping
- [ ] Set up logs aggregation
- [ ] Configure health check monitoring

---

## Troubleshooting

### PostgreSQL Connection Issues

**Problem**: `could not connect to server`

```bash
# Check if PostgreSQL is running
docker compose ps

# Restart PostgreSQL
docker compose restart app-db

# Check logs
docker compose logs app-db
```

### Migration Errors

**Problem**: `alembic upgrade head` fails

```bash
# Check migration status
alembic current

# Try stamp then upgrade
alembic stamp head
alembic upgrade head
```

### LLM Provider Issues

**Problem**: `Unable to connect to LLM provider`

1. Check API key is set correctly in `.env`
2. Verify network connectivity
3. Check provider status page
4. Review logs: `docker compose logs backend`

### Embedding Dimension Mismatch

**Problem**: Embeddings fail after switching providers

The application automatically detects dimension mismatches at startup. If you see errors:

1. Restart the backend container
2. The application will automatically resize vector columns
3. Wait for embeddings to regenerate (check `/api/v1/embeddings/status`)

### Frontend Build Issues

**Problem**: `npm run build` fails

```bash
# Clear node_modules and reinstall
rm -rf node_modules
npm install
```

### Rate Limit Errors

**Problem**: `429 Too Many Requests`

- Wait for the rate limit window to reset
- Reduce request frequency
- Check the rate limit headers in responses

### Port Conflicts

**Problem**: `Port already in use`

```bash
# macOS/Linux: Find process using port
lsof -i :8000

# Windows: Find process using port
netstat -ano | findstr :8000

# Stop the conflicting process or use a different port
```

---

## Next Steps

After setting up QueryWise:

1. **Add your first connection**: Go to the Connections page and add a target database
2. **Set up semantic context**: Add glossary terms, metrics, and sample queries
3. **Explore the API**: Check the API docs at http://localhost:8000/docs
4. **Try a query**: Ask a natural language question in the chatbot

---

## Getting Help

- **Documentation**: Check `/docs` in the codebase
- **API Docs**: http://localhost:8000/docs
- **Logs**: `docker compose logs -f backend`
- **Issues**: Report bugs on GitHub

---

## Additional Resources

- [Architecture Documentation](./arch.md)
- [Component Documentation](./02-components-agents-and-tooling.md)
- [API Contracts](./03-data-and-interface-contracts.md)
- [Semantic Implementation](./semantic-implementation.md)