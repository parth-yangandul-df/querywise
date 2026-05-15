# QueryWise React Admin UI

This app is the React-based administration surface for QueryWise. It is used for connection management, schema inspection, and semantic metadata authoring.

## Responsibilities

- authentication flows for the admin experience
- database connection CRUD
- schema introspection workflows
- glossary, metric, dictionary, sample-query, and knowledge management

## Run locally

```bash
cd frontend
npm install
npm run dev
```

Default URL: `http://localhost:5173`

## Build

```bash
npm run build
```

## Backend expectation

By default the app expects the backend API at `http://localhost:8000`. Configure the matching environment variable when running against a different backend host.

## Related docs

- `../README.md`
- `../docs/onboarding-guide.md`
- `../docs/03-data-and-interface-contracts.md`
