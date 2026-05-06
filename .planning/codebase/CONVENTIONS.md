# Code Conventions

## Python (Backend)

### Formatting & Linting
- **Tool:** Ruff
- **Line length:** 100 characters
- **Target:** Python 3.11+
- **Rules enabled:** `E` (pycodestyle errors), `F` (pyflakes), `I` (isort), `N` (naming), `UP` (pyupgrade), `B` (flake8-bugbear)

### Type Checking
- **Tool:** mypy
- **Strict mode enabled**

### Code Style
- **Async everywhere:** All DB operations, HTTP calls, and LLM calls are async
- **ORM models:** UUID primary keys, `created_at`/`updated_at` timestamps
- **No explicit `any`:** TypeScript strict mode enforced

## TypeScript (Frontend)

### Formatting & Linting
- **Tool:** ESLint (flat config)
- **Plugins:** `@eslint/js`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`
- **Build:** Vite with TypeScript (`tsc -b && vite build`)

### Code Style
- **React 19** with functional components and hooks
- **No explicit `any`:** Strict TypeScript mode
- **Component patterns:** Follow shadcn/ui conventions in chatbot-frontend

## Common Patterns

### API Routes
- All routes under `/api/v1`
- Defined in `app/api/v1/endpoints/`
- Aggregated in `app/api/v1/router.py`

### Services
- Business logic in `app/services/`
- Never in endpoints directly

### Connectors
- Extend `BaseConnector` ABC in `app/connectors/`
- Register in `connector_registry.py`
- Built-in: PostgreSQL (`asyncpg`), SQL Server (`aioodbc`)

### LLM Providers
- Extend `BaseLLMProvider` ABC in `app/llm/providers/`
- Register via `provider_registry`
- Built-in: Anthropic, OpenAI, Ollama, OpenRouter, Groq