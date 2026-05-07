# QueryWise Onboarding Guide

## Audience

Use this guide when you are setting up QueryWise locally for the first time or coming back after a long gap.

## What you are starting

You are running three cooperating applications:

- FastAPI backend on `:8000`
- React admin UI on `:5173`
- Angular chat UI on `:4200`

The backend stores its own metadata, sessions, and semantic assets in PostgreSQL with pgvector.

## Prerequisites

| Requirement | Recommended version |
|---|---|
| Python | 3.12 |
| Node.js | 18+ |
| Docker Desktop | current |
| Git | current |

You also need one LLM provider configured, unless you are using Ollama locally.

## Fast path: run the whole stack with Docker

```bash
cp .env.example .env
docker compose up
```

Then open:

- React admin UI: `http://localhost:5173`
- Angular chat UI: `http://localhost:4200`
- API docs: `http://localhost:8000/docs`

## Recommended local development path

### 1. Create `.env`

Start from `.env.example` and set at minimum:

```env
ENCRYPTION_KEY=your-secret
JWT_SECRET=your-jwt-secret
DEFAULT_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
```

If you prefer OpenRouter:

```env
DEFAULT_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=deepseek/deepseek-v3.2
RESOLVER_MODEL=openai/gpt-4.1-nano
INTERPRETER_MODEL=meta-llama/llama-3.1-8b-instruct
```

If you prefer Ollama:

```env
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_BASE_URL=http://localhost:11434
EMBEDDING_DIMENSION=768
```

### 2. Start the metadata database

```bash
docker compose up app-db -d
```

### 3. Start the backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[llm,dev,sqlserver]"
alembic upgrade head
uvicorn app.main:app --reload
```

### 4. Start the React admin UI

```bash
cd frontend
npm install
npm run dev
```

### 5. Start the Angular chat UI

```bash
cd angular-test
npm install
npm run start
```

## First-run workflow

1. Open the React admin UI
2. Sign in if your environment requires auth
3. Create a database connection
4. Test the connection
5. Run schema introspection
6. Add or import semantic metadata if needed
7. Open the Angular chat UI and ask a query against that connection

## Working with connections

### PostgreSQL from Docker to host

Use `host.docker.internal` when the target database runs on the host machine and QueryWise runs in Docker.

Example:

```text
postgresql://user:password@host.docker.internal:5432/mydb
```

### SQL Server

Use an ODBC-style connection string, for example:

```text
SERVER=localhost,1433;DATABASE=master;UID=sa;PWD=your-password;Encrypt=yes;TrustServerCertificate=yes;
```

On Windows, ensure an appropriate SQL Server ODBC driver is installed.

## Useful health checks

```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
curl http://localhost:8000/api/v1/embeddings/status
```

## Common developer tasks

Backend checks:

```bash
cd backend
pytest
ruff check .
mypy .
```

Frontend checks:

```bash
cd frontend
npm run build

cd angular-test
npm run build
```

## Where to read next

- [./01-system-architecture-and-execution-flow.md](./01-system-architecture-and-execution-flow.md)
- [./03-data-and-interface-contracts.md](./03-data-and-interface-contracts.md)
- [./QA_TESTING.md](./QA_TESTING.md)