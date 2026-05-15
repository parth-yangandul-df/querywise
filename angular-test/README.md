# QueryWise Angular Chat UI

This app is the end-user chat client for QueryWise.

## Responsibilities

- creates or resumes a chat session for the selected connection
- sends streamed query requests to `/api/v1/query/stream`
- renders progress stages, assistant responses, clarifications, and errors
- displays result tables with search, sorting, pagination, and CSV export

## Run locally

```bash
cd angular-test
npm install
npm run start
```

Default URL: `http://localhost:4200`

## Build

```bash
npm run build
```

## Runtime notes

- the chat service stores session IDs per connection in `sessionStorage`
- recent questions are cached locally
- backend progress arrives over server-sent events
- the result table is client-side interactive after the final result arrives

## Main source files

- `src/app/services/chat.service.ts`
- `src/app/chat/chat.component.ts`
- `src/app/chat/chat.component.html`
- `src/app/chat/chat.component.css`

## Related docs

- `../README.md`
- `../docs/QA_TESTING.md`
- `../docs/03-data-and-interface-contracts.md`
