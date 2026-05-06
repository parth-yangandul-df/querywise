# QueryWise Roadmap

## Phases

- [x] **Phase 1: Foundation** - Basic FastAPI setup, LLM providers, semantic layer, connection management
- [x] **Phase 5: LangGraph Domain Tool Pipeline** - Replace LLM SQL generation with embedding-based intent classification and PRMS domain tools (completed 2026-03-26)
- [x] **Phase 6: Context-Aware Domain Tools** - Stateful follow-up handling, TurnContext propagation, domain tool subquery refinement, fallback_intent wiring (completed 2026-04-02)
- [x] **Phase 7: QueryPlan Compiler** - Replace SQL subquery wrapping with a structured QueryPlan state model that accumulates typed filters across turns and compiles SQL deterministically (completed 2026-04-06)

---

## Phase Details

### Phase 1: Foundation
**Goal**: Core application infrastructure running end-to-end
**Status:** Complete
**Depends on**: Nothing
**Requirements**: N/A (pre-planning)
**Success Criteria**:
  1. FastAPI server starts and serves API requests
  2. LLM providers (Anthropic, OpenAI, Ollama) are configurable via env vars
  3. Semantic layer (glossary, metrics, dictionary) stores and retrieves metadata
  4. Database connections can be created, tested, and used to execute queries
**Plans**: N/A

---

### Phase 5: LangGraph Domain Tool Pipeline
**Goal**: Replace `execute_nl_query()` with a LangGraph `StateGraph` that routes NL questions to 24 pre-built PRMS domain SQL tools (via embedding-based intent classification) or falls back to the existing LLM generation chain
**Status:** Complete (2026-03-26)
**Depends on**: Phase 1
**Requirements**: LG-01, LG-02, LG-03, LG-04, LG-05, LG-06, LG-07, LG-08, LG-09, LG-10, LG-11, LG-12, LG-13, LG-14, LG-15, LG-16
**Success Criteria**:
  1. NL questions matching a known PRMS intent route to domain SQL tools without LLM generation
  2. Low-confidence questions fall back to the existing LLM pipeline transparently
  3. 0-row domain tool results attempt a fallback intent before escalating to LLM
  4. SQL Server params bug is fixed — parameterized queries execute correctly
  5. Embedding unavailability degrades gracefully (app starts, pipeline routes to LLM fallback)
  6. `generate_sql_only()` and `execute_raw_sql()` are completely unchanged

**Plans**:
- [x] 05-01-PLAN.md — Feature branch, LangGraph deps, GraphState, 24-intent catalog, test scaffolding
- [x] 05-02-PLAN.md — Intent classifier node (cosine similarity) + param extractor node
- [x] 05-03-PLAN.md — SQLServer connector bug fix + 4 PRMS domain agents + domain registry
- [x] 05-04-PLAN.md — result_interpreter, llm_fallback, write_history nodes + graph assembly (with 0-row topology)
- [x] 05-05-PLAN.md — Wire graph into query_service.py + startup hook + full test suite

### Phase 6: Context-Aware Domain Tools & Stateful Follow-Up

**Goal:** Make the LangGraph pipeline stateful across conversation turns so follow-up queries ("Which of these know Python?", "Filter by active only") route to domain tools instead of falling back to LLM — by adding structured TurnContext propagation, follow-up detection in intent classification, param inheritance in param extraction, subquery-based domain tool refinement mode, and fallback_intent wiring for 0-row results
**Status:** Complete (2026-04-02)
**Depends on:** Phase 5
**Requirements**: CTX-01, CTX-02, CTX-03, CTX-04, CTX-05, CTX-06, CTX-07, CTX-08, CTX-09, CTX-10
**Success Criteria**:
  1. Follow-up queries like "Which of these know Python?" after "Show benched resources" route to domain tool (not LLM) via subquery refinement
  2. Params from prior turn carry forward to follow-up params extraction when not overridden
  3. Intent classifier detects thin follow-up patterns and inherits prior domain/intent with high confidence
  4. 0-row domain tool results try a configured fallback_intent before escalating to LLM (all 29 catalog entries have fallback_intent set)
  5. Backend API response includes structured turn_context (intent, domain, params, columns, sql)
  6. chatbot-frontend ChatPanel and StandaloneChatPage send last_turn_context on every follow-up request
  7. chatbot-frontend ChatPanel sends session_id (currently missing)

**Plans:** 5/5 plans executed

Plans:
- [x] 06-01-PLAN.md — TurnContext schema foundation (backend schemas, GraphState, query_service, endpoint)
- [x] 06-02-PLAN.md — fallback_intent wiring for all 24 active catalog entries
- [x] 06-03-PLAN.md — Context-aware classify_intent (follow-up fast path) + param inheritance in extract_params
- [x] 06-04-PLAN.md — Domain tool subquery refinement (base_domain helpers + ResourceAgent._run_refinement)
- [x] 06-05-PLAN.md — Frontend TurnContext tracking (types, queryApi, ChatWidget session, ChatPanel, StandaloneChatPage)

### Phase 7: QueryPlan Compiler

**Goal:** Replace SQL subquery wrapping with a structured QueryPlan state model that accumulates typed filters across conversation turns and compiles SQL deterministically — with zero RBAC regressions, a safe feature-flag rollout (`USE_QUERY_PLAN_COMPILER`), and full regression test coverage before retiring the old path.
**Status:** Complete (2026-04-06)
**Depends on:** Phase 6
**Requirements**: QP-01, QP-02, QP-03, QP-04

**Plans:** 4/4 plans executed

Plans:
- [x] 07-01-PLAN.md — QueryPlan Foundation (query_plan.py, GraphState, query_service, feature flag)
- [x] 07-02-PLAN.md — Filter Extraction + Plan Update (FieldRegistry, filter_extractor, plan_updater, graph wiring)
- [x] 07-03-PLAN.md — SQL Compiler + Domain Agent Rewrite (sql_compiler, base_domain flag, regression tests, retirements)
- [x] 07-04-PLAN.md — Semantic Layer Executable (glossary→filters, dict value_map, metric injection)

---

### Phase 8: Context-Aware Hybrid AI Query System

**Goal:** Upgrade QueryWise into a production-grade conversational query engine that maintains robust multi-turn context, uses deterministic logic wherever possible, uses LLM only where necessary (controlled + structured), minimizes cost and failure propagation, and compiles syntactically correct SQL via structured query plans (NOT raw LLM SQL).
**Status:** Complete (2026-04-07)
**Depends on:** Phase 7
**Requirements**: HYB-01, HYB-02, HYB-03, HYB-04, HYB-05, HYB-06, HYB-07, HYB-08, HYB-09, HYB-10, HYB-11, HYB-12, HYB-13, HYB-14, HYB-15, HYB-16, HYB-17, HYB-18, HYB-19, HYB-20, HYB-21, HYB-22, HYB-23, HYB-24, HYB-25, HYB-26

**Plans:** 6/6 plans executed

Plans:
- [x] 08-01-PLAN.md — GraphState Extension + Follow-up Detection
- [x] 08-02-PLAN.md — LLM Structured Extraction + Confidence Scoring
- [x] 08-03-PLAN.md — Deterministic Override + Conflict Resolution
- [x] 08-04-PLAN.md — 6-Level Fallback Ladder + Context Recovery
- [x] 08-05-PLAN.md — Query Caching + Observability
- [x] 08-06-PLAN.md — Semantic Integration + E2E Pipeline

### Phase 9: Query Engine Refactor

**Goal:** Replace the current brittle routing (Groq extractor, graph branches, domain agents, SQL compiler, fallback logic, turn-context heuristics) with a single canonical pipeline: Conversation Resolver → Query Planner → **Plan Validator** → Capability Matcher → Strategy Selector → Executor → Result Narrator → State Store.

**Key Intelligence Layers Added:**
- **Plan Validator** (NEW): Validates per-filter confidence, resolves entities against known metadata, detects contradictions with prior state, applies clarification policy
- **Per-filter confidence**: Not just global confidence — each filter has its own confidence score (0.0-1.0)
- **Entity resolution**: Matches filter values against client tables, project names, skill dictionaries, status vocabularies
- **Contradiction detection**: Flags conflicts between current filters and prior state
- **Clarification policy**: Smart disambiguation based on confidence, ambiguity, and contradictions

**Status:** Planned
**Depends on:** Phase 8
**Requirements**: QE-01, QE-02, QE-03, QE-04, QE-05, QE-06, QE-07, QE-08, QE-09, QE-10, QE-11, QE-12, QE-13, QE-14, QE-15, QE-16, QE-17, QE-18, QE-19, QE-20, QE-21

**Sub-phases:**
1. Core Contracts (QueryPlan, ConversationState, PlanDecision, ExecutionStrategy types)
2. Config Cleanup (replace scattered query config)
3. Capability Catalog Extraction (trusted SQL → structured capabilities)
4. Planner Implementation (structured planning, no SQL output)
5. Capability Matcher (full/partial/no match scoring)
6. Strategy Selector (reject/clarify/template/generate routing)
7. Template Executor (trusted fast path)
8. Generation Executor (controlled fallback)
9. Execution Guardrail Layer (centralized RBAC, validation, limits)
10. Conversation State System (durable thread state, Postgres-backed)
11. Session Ownership and Security Fix (user-scoped sessions, migration)
12. Query Service Rewrite (clean orchestrator)
13. API Layer Update (thin, stable endpoints)
14. Retrieval Split (lightweight vs heavyweight)
15. Observability (metrics, latency tracking)
16. Legacy Retirement (delete old graph stack)

**Success Criteria:**
  1. Common business questions route to trusted predefined capabilities reliably
  2. Novel questions still work through generation fallback
  3. Multi-turn refinement is materially more reliable with persistent state
  4. Topic switching is explicit and stable
  5. One canonical pipeline, one QueryPlan contract, one ConversationState model
  6. Lower p95 latency for common asks, lower LLM cost
  7. Legacy graph stack fully removed
  8. Plan Validator stage validates plans before matcher — per-filter confidence, entity resolution, contradiction detection
  9. Per-filter confidence in FilterClause (0.0-1.0, default 1.0)
  10. Entity resolution against known metadata (clients, projects, skills, statuses)
  11. Semantic regression suite — 20+ test cases proving system smartness is real (not vibes)

Plans:
- [ ] 09-01-PLAN.md — Core Contracts + Config Cleanup (sub-phases 1–2)
- [ ] 09-02-PLAN.md — Capability Catalog Extraction (sub-phase 3)
- [ ] 09-03-PLAN.md — Planner Implementation (sub-phase 4)
- [ ] 09-04-PLAN.md — Capability Matcher + Strategy Selector (sub-phases 5–6)
- [ ] 09-05-PLAN.md — Template Executor + Generation Executor (sub-phases 7–8)
- [ ] 09-06-PLAN.md — Execution Guardrail Layer (sub-phase 9)
- [ ] 09-07-PLAN.md — Conversation State System + Session Ownership (sub-phases 10–11)
- [ ] 09-08-PLAN.md — Query Service Rewrite + API Layer Update (sub-phases 12–13)
- [ ] 09-09-PLAN.md — Retrieval Split + Observability (sub-phases 14–15)
- [ ] 09-10-PLAN.md — Legacy Retirement (sub-phase 16)

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | N/A | Complete | 2026-03-01 |
| 5. LangGraph Domain Tool Pipeline | 5/5 | Complete | 2026-03-26 |
| 6. Context-Aware Domain Tools | 5/5 | Complete | 2026-04-02 |
| 7. QueryPlan Compiler | 4/4 | Complete | 2026-04-06 |
| 8. Context-Aware Hybrid | 6/6 | Complete | 2026-04-07 |
| 9. Query Engine Refactor | 0/10 | Planned | — |
