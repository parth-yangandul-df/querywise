# Testing Practices

## Backend Testing

### Test Framework
- **Tool:** pytest
- **Async support:** pytest-asyncio with `asyncio_mode = "auto"`
- **Test paths:** `backend/tests/`

### Test Structure
```
backend/tests/
├── conftest.py              # Shared fixtures
├── e2e/                     # End-to-end tests (require running backend + DB)
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_connections.py
│   ├── test_health.py
│   ├── test_pipeline_e2e.py
│   ├── test_query.py
│   ├── test_query_history.py
│   ├── test_query_stream.py
│   ├── test_semantic_layer.py
│   └── test_sessions.py
├── semantic/                # Semantic layer tests
│   ├── test_relationship_inference.py
│   └── test_schema_linker_sqlserver.py
└── unit tests:
    ├── test_domain_agents.py
    ├── test_field_registry.py
    ├── test_graph_nodes.py
    ├── test_graph_state.py
    ├── test_graph_state_extension.py
    ├── test_intent_catalog.py
    ├── test_intent_classifier.py
    ├── test_observability.py
    ├── test_query_plan_model.py
    ├── test_queryplan_integration.py
    ├── test_rate_limit_handling.py
    ├── test_sql_compiler.py
    └── test_subquery_refinement.py
```

### Test Markers
- `@pytest.mark.e2e` — End-to-end tests requiring a running backend and real database connection

### Test Patterns
- Use `@pytest.mark.asyncio` for async test functions
- Fixtures defined in `conftest.py` for mock DB sessions, query results, embedding stubs
- Use `unittest.mock.AsyncMock` and `unittest.mock.patch` for external dependencies

### Running Backend Tests
```bash
cd backend
pytest                    # Run all tests
pytest tests/e2e/         # Run only e2e tests
pytest -m "not e2e"       # Skip e2e tests
pytest --cov=app          # With coverage
```

## Frontend Testing

### Current State
- **No test suite implemented** in either `frontend/` or `chatbot-frontend/`
- No `vitest`, `jest`, or other test framework configured
- Lint and build commands available, but no test commands

### Recommended Patterns (when implemented)
- Use Vitest (aligned with Vite build tool)
- Component tests with React Testing Library
- Test files alongside components as `*.test.tsx` or `*.spec.tsx`

## Coverage

### Backend
- Unit tests cover individual graph nodes, agents, semantic layer components
- E2E tests cover full query pipeline, auth, connections, health
- No formal coverage threshold currently enforced

### Frontend
- Coverage not yet established