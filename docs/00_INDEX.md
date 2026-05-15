# QueryWise Documentation Index

This is the curated documentation set for the current codebase. If two documents overlap, prefer the files listed here.

## Start here

| Document | Use it for |
|---|---|
| [../README.md](../README.md) | Project overview and fastest path to first run |
| [./onboarding-guide.md](./onboarding-guide.md) | Local setup and day-one developer workflow |
| [./QA_TESTING.md](./QA_TESTING.md) | Current manual QA scenarios |

## Architecture and design

| Document | Use it for |
|---|---|
| [./01-system-architecture-and-execution-flow.md](./01-system-architecture-and-execution-flow.md) | End-to-end request flow and LangGraph topology |
| [./02-components-agents-and-tooling.md](./02-components-agents-and-tooling.md) | Ownership map of the major backend and frontend components |
| [./03-data-and-interface-contracts.md](./03-data-and-interface-contracts.md) | Database entities, API contracts, and stream event shapes |
| [./04-operations-behavior-and-limitations.md](./04-operations-behavior-and-limitations.md) | Runtime behavior, health checks, feature flags, and known limits |
| [./semantic-layer.md](./semantic-layer.md) | How context retrieval and semantic metadata work |
| [./rbac-design.md](./rbac-design.md) | Authentication, authorization, and scoped querying |
| [./TECH_STACK.md](./TECH_STACK.md) | Concise stack reference |

## UI-specific docs

| Document | Use it for |
|---|---|
| [../frontend/README.md](../frontend/README.md) | React admin UI development |
| [../angular-test/README.md](../angular-test/README.md) | Angular chat UI development |

## Operational quick links

- Health: `http://localhost:8000/api/v1/health`
- Ready: `http://localhost:8000/api/v1/ready`
- OpenAPI: `http://localhost:8000/docs`
- Embedding progress: `http://localhost:8000/api/v1/embeddings/status`

## Notes on removed docs

Off-topic prompt dumps and generic architecture notes have been removed from `docs/`. Root-level legacy test banks are still present, but the canonical QA source is [./QA_TESTING.md](./QA_TESTING.md).