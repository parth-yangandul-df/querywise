# QueryWise Technology Stack

## Programming Languages

- **Python 3.11+** — Backend API, LLM integrations, database operations
- **TypeScript** — Frontend applications
- **JavaScript** — Frontend build tooling

## Backend

### Frameworks
- **FastAPI** — Web framework (async, type hints, OpenAPI generation)
- **Uvicorn** — ASGI server
- **SQLAlchemy 2.0+** — ORM (async mode)
- **Alembic** — Database migrations
- **LangGraph** — Stateful graph for LLM agent orchestration

### Key Libraries
- **asyncpg** — Async PostgreSQL driver
- **pgvector** — Vector similarity search for embeddings
- **httpx** — Async HTTP client
- **pydantic** — Data validation
- **pydantic-settings** — Settings management
- **tenacity** — Retry logic
- **loguru** — Structured logging
- **prometheus-fastapi-instrumentator** — Metrics
- **PyJWT** — JWT authentication
- **passlib/bcrypt** — Password hashing
- **sqlparse** — SQL parsing/sanitization
- **sse-starlette** — Server-sent events for streaming

### LLM Libraries
- **anthropic** — Anthropic API client
- **openai** — OpenAI API client
- **langchain-core** — LangChain abstractions

### Database Connectors
- **PostgreSQL** — via asyncpg (connection pooling)
- **SQL Server** — via aioodbc (lazy-loaded, optional)

### Optional Dependencies
- **aioodbc** — SQL Server connector (requires pyodbc)

### Development Tools
- **pytest** — Testing
- **pytest-asyncio** — Async test support
- **ruff** — Linting (E, F, I, N, UP, B rules)
- **mypy** — Type checking

## Frontend (Mantine UI)

### Framework
- **React 19** — UI library
- **Vite** — Build tool
- **TypeScript** — Type safety
- **React Router** — Routing

### UI Libraries
- **@mantine/core** — Component library
- **@mantine/form** — Form handling
- **@mantine/notifications** — Notifications
- **@mantine/code-highlight** — SQL syntax highlighting
- **@tabler/icons-react** — Icons
- **@monaco-editor/react** — SQL editor

### Data Fetching
- **@tanstack/react-query** — Server state management
- **axios** — HTTP client

## Chatbot Frontend (shadcn/ui + Tailwind)

### Framework
- **React 19** — UI library
- **Vite** — Build tool
- **TypeScript** — Type safety
- **React Router** — Routing
- **Tailwind CSS** — Styling

### UI Components
- **shadcn/ui** — Radix UI primitives with Tailwind
- **@radix-ui/** — Headless UI components
- **lucide-react** — Icons
- **framer-motion** — Animations
- **clsx / tailwind-merge** — Class utilities

### Data Fetching
- **@tanstack/react-query** — Server state management
- **axios** — HTTP client

## Databases

### Application Database (pgvector)
- **PostgreSQL 16** with **pgvector** extension
- Stores: metadata, glossary terms, embeddings, query history, knowledge documents
- Default port: 5432

### Target Databases (User Connections)
- **PostgreSQL** — Via built-in connector
- **SQL Server** — Via optional aioodbc connector

## Infrastructure

### Docker Services
- **app-db** — PostgreSQL + pgvector (pgvector/pgvector:pg16)
- **backend** — FastAPI application
- **frontend** — Mantine UI (port 5173)
- **chatbot-frontend** — React + Tailwind (port 5174)
- **ollama** — Optional local LLM (Docker profile)
- **pgadmin** — PostgreSQL admin UI (Docker profile, port 5050)

## Environment Configuration

### Key Variables
- `DATABASE_URL` — App metadata DB connection
- `ENCRYPTION_KEY` — Fernet key for connection string encryption
- `DEFAULT_LLM_PROVIDER` — LLM provider selection
- `EMBEDDING_DIMENSION` — Vector size (1536 for OpenAI, 768 for Ollama)
- `CORS_ORIGINS` — Allowed origins