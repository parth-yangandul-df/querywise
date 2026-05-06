# QueryWise Requirements

## Phase 5: LangGraph Domain Tool Pipeline

### LG-01: LangGraph Dependencies
- Add `langgraph>=0.2` and `langchain-core>=0.3` to `backend/pyproject.toml` under `llm` extras
- Both packages must be importable after install

### LG-02: GraphState TypedDict
- Define `GraphState` TypedDict in `backend/app/llm/graph/state.py`
- Must contain all 24 required keys: question, connection_id, connector_type, connection_string, timeout_seconds, max_rows, db, domain, intent, confidence, params, sql, result, generated_sql, retry_count, explanation, llm_provider, llm_model, answer, highlights, suggested_followups, execution_id, execution_time_ms, error

### LG-03: 24-Intent Catalog
- Define `INTENT_CATALOG` in `backend/app/llm/graph/intent_catalog.py`
- Exactly 24 entries across 4 domains: Resource (9), Client (5), Project (6), Timesheet (4)
- Each `IntentEntry` has: name, domain, description, embedding, sql_fallback_template (optional), fallback_intent (optional)
- Intent names must be unique; domains restricted to: resource, client, project, timesheet

### LG-04: Catalog Pre-Embedding
- `ensure_catalog_embedded()` pre-embeds all 24 catalog descriptions at startup
- Idempotent — safe to call multiple times (asyncio.Lock guarded)
- Uses `embed_text()` from `app/services/embedding_service.py`
- If embedding provider is unavailable: log warning and skip — do NOT crash startup

### LG-05: Intent Classifier Node
- `classify_intent` node embeds the question and picks best catalog match via cosine similarity
- Sets: domain, intent, confidence in returned state dict
- Reads threshold from `TOOL_CONFIDENCE_THRESHOLD` env var (default 0.78)
- If catalog not yet embedded, calls `ensure_catalog_embedded()` lazily
- If embedding fails: catch exception, route to `llm_fallback` (graceful degradation)

### LG-06: Routing Edge + Param Extractor
- `route_after_classify(state)` returns `"run_domain_tool"` if confidence >= threshold, else `"llm_fallback"`
- `extract_params(state)` extracts skill, start_date, end_date, resource_name from question using regex only (no LLM)
- No extraction → params={} (empty dict)

### LG-07: SQLServer Connector Bug Fix
- Fix `backend/app/connectors/sqlserver/connector.py`: `_run_query()` currently ignores `params` argument entirely
- Update `_run_query()` to accept and pass params tuple to `cursor.execute(sql, params_tuple)`
- Update `execute_query()` signature: `params: tuple[Any, ...] | None = None`
- Update `backend/app/connectors/base_connector.py` abstract method signature to match

### LG-08: Resource Domain Agent
- `ResourceAgent` handles all 9 resource intents with parameterized SQL templates
- Uses `?` positional placeholders (SQL Server / pyodbc style)
- Bare table names (no `dbo.` prefix)
- Unknown intent raises `ValueError`

### LG-09: Client, Project, Timesheet Domain Agents
- `ClientAgent` handles 5 client intents
- `ProjectAgent` handles 6 project intents
- `TimesheetAgent` handles 4 timesheet intents — all valid-entry queries include `IsApproved=1 AND IsDeleted=0 AND IsRejected=0`
- Unknown intent raises `ValueError` in each agent

### LG-10: Domain Registry + run_domain_tool Node
- `DOMAIN_REGISTRY` maps domain name → agent class
- `run_domain_tool(state)` looks up state["domain"], instantiates agent, calls `execute(state)`
- Unknown domain raises `ValueError`
- Agent `execute()` returns: sql, result, llm_provider="domain_tool", llm_model=intent_name

### LG-11: 0-Row Fallback Chain
- After `run_domain_tool`: if `result.row_count == 0`:
  1. If `IntentEntry.fallback_intent` is defined → run that intent's SQL (1 hop max, no chaining)
  2. If fallback intent also returns 0 rows (or none defined) → route to `llm_fallback`
- SQL execution errors (exceptions) → immediate AppError, no retry, no LLM fallback
- `interpret_result` node only reached when rows > 0

### LG-12: Result Interpreter Node
- `interpret_result` node wraps existing `ResultInterpreterAgent` unchanged
- If result has rows: calls `interpreter.interpret()`, sets answer, highlights, suggested_followups
- If result has no rows: sets answer=None, highlights=[], suggested_followups=[]

### LG-13: LLM Fallback Node
- `llm_fallback` node reuses existing `QueryComposerAgent`, `SQLValidatorAgent`, `ErrorHandlerAgent` unchanged
- Mirrors current `query_service.execute_nl_query()` LLM logic exactly
- Sets: sql, result, generated_sql, retry_count, llm_provider, llm_model, explanation

### LG-14: Write History Node + Graph Assembly
- `write_history` node creates `QueryExecution` record, calls `db.add()` + `db.flush()`
- Sets: execution_id, execution_time_ms
- `get_compiled_graph()` returns a compiled LangGraph `StateGraph` singleton
- Graph topology reflects the 0-row conditional edge (LG-11)

### LG-15: query_service.py Integration
- Replace `execute_nl_query()` body with `get_compiled_graph().ainvoke(initial_state)`
- Response dict shape preserved exactly (same 17 keys as original)
- `generate_sql_only()` and `execute_raw_sql()` completely unchanged

### LG-16: Startup Hook
- `main.py` lifespan calls `ensure_catalog_embedded()` after `ensure_embedding_dimensions()`, before `auto_setup_sample_db()`
- Wrapped in try/except — failure logs warning but does NOT prevent startup

---

## Phase 7: QueryPlan Compiler

### QP-01: QueryPlan Model and Foundation
- Define `QueryPlan` and `FilterClause` Pydantic v2 models in `backend/app/llm/graph/query_plan.py`
- `FilterClause`: `field` (registry-validated), `op: Literal["eq","in","lt","gt","between"]`, `values: list[str]` (sanitized, max 50), SQL injection guard on values
- `QueryPlan` fields: `domain`, `intent`, `filters: list[FilterClause]`, `base_intent_sql: str`, `schema_version: Literal[1]`
- `QueryPlan.from_untrusted_dict()` classmethod for safe deserialization; `to_api_dict()` for serialization
- Add `query_plan: dict | None` to GraphState TypedDict (stored as dict, not raw Pydantic — follows Phase 6 pattern)
- Add `use_query_plan_compiler: bool = False` feature flag to Settings (reads from `USE_QUERY_PLAN_COMPILER` env var)
- Update `query_service.py` to deserialize QueryPlan from graph state for `base_sql` construction, include in `turn_context` response, fall back to existing `_prior_sql` logic when None

### QP-02: Filter Extraction and Plan Update Pipeline
- Create `FieldRegistry` in `backend/app/llm/graph/nodes/field_registry.py` with all PRMS filterable fields across 5 domains (resource, client, project, timesheet, user_self), column mappings, aliases, and multi-value flags
- `FieldConfig` dataclass: `field_name`, `column_name`, `multi_value`, `sql_type`, `aliases`, `domains`
- `validate_registry_completeness()` raises `StartupIntegrityError(RuntimeError)` if any domain-intent pair has no registered fields
- Create `filter_extractor` node (regex-first extraction with LLM fallback stub) — reuses patterns from `param_extractor.py`, validates all extracted fields against FieldRegistry, drops unknowns safely
- Create `plan_updater` node — accumulates filters across turns: multi-value fields append, date ranges last-wins, boolean/scalar last-wins, domain/intent switch creates fresh plan
- Wire `extract_filters → update_query_plan` into LangGraph pipeline, replace `extract_params` node
- Move `param_extractor.py` to `_deprecated/` folder (not deleted)

### QP-03: SQL Compiler and Domain Agent Rewrite
- Create `sql_compiler.py` with `BASE_QUERIES` dict containing all 24 active PRMS intent SQL templates, each with `{select_extras}` and `{join_extras}` named tokens
- `build_in_clause(column, values)` with edge guards: empty → `"1=0"`, single → `"field=?"`, >2000 → `ValueError`
- `compile_query(plan, resource_id=None, metrics=None)` — produces deterministic SQL with correct WHERE clauses, parameter tuples, RBAC guard (raises ValueError if `plan.domain == "user_self" and resource_id is None`)
- Rewrite `BaseDomainAgent.execute()` with feature flag branch: flag ON → `compile_query()` path, flag OFF → existing `_try_refinement()` path unchanged
- 5 regression flow tests: resource chain, project filter chain, timesheet date chain, topic switch recovery, LLM fallback→domain tool
- Wire `StartupIntegrityError` into `main.py` lifespan hook
- Mark `refinement_registry.py` as deprecated (not deleted — kept for rollback safety), add deprecation warning to `_try_refinement()`

### QP-04: Semantic Layer Wiring
- Create `semantic_resolver.py`: `resolve_glossary_hints()` returns available field names from glossary terms for filter extraction hints, `load_value_map()` loads dictionary value_map at startup, `normalize_value()` maps user-friendly values to DB values
- Wire glossary hints into `filter_extractor` — use glossary terms to disambiguate ambiguous extractions, degrade gracefully when unavailable
- Wire value_map normalization into `plan_updater` — normalize filter values through dictionary mappings before accumulation
- Add `MetricFragment` dataclass to `sql_compiler`: `select_expr`, `join_clause`, `requires_group_by`
- Update `compile_query()` to accept metrics list and inject `{select_extras}` / `{join_extras}` tokens, add GROUP BY when required
- Keyword-based metric detection stub (full LLM detection deferred)
- 4 end-to-end integration tests: glossary pipeline, value_map pipeline, metric pipeline, full semantic pipeline

---

## Phase 8: Context-Aware Hybrid AI Query System

### HYB-01: GraphState Extension for Hybrid Mode
- Extend `GraphState` TypedDict with: session_id, last_query, last_query_embedding, current_query_embedding, semantic_similarity, follow_up_type, confidence_breakdown
- Store as dict (following Phase 6/7 pattern), not raw Pydantic

### HYB-02: Session and Embedding Storage
- Store session_id across conversation turns
- Store last_query_embedding for similarity comparison
- Compute current_query_embedding at classify_intent

### HYB-03: Follow-up Detection Node
- Create `detect_followup_type()` function
- Inputs: current_query_embedding, last_query_embedding, current_intent, last_intent
- Returns: "refine" | "replace" | "new"
- Semantic similarity > 0.7 = "refine"
- Intent mismatch = "new"

### HYB-04: Semantic Similarity Calculation
- Use cosine similarity between embeddings
- Store semantic_similarity in GraphState for observability

### HYB-05: Follow-up Type Classification
- "refine": semantic_similarity > 0.7 and same intent
- "replace": same field detected in filters
- "new": intent mismatch or low similarity

### HYB-06: LLM Structured Extraction (Single Call)
- Single LLM call per query (not per filter)
- Strict JSON output: {filters, sort, limit, follow_up_type}
- No explanation, no hallucinated fields
- Uses Llama 3.3 70B (already configured as DEFAULT_LLM_MODEL)

### HYB-07: JSON Extraction with Field Validation
- Validate extracted fields against FieldRegistry
- Drop unknown fields safely
- Use semantic_resolver to map user terms to canonical names

### HYB-08: Confidence Scoring
- calculate_confidence(extracted, valid_fields, matches_schema) returns float
- Formula: valid_json (+0.3) + valid_fields (+0.3) + matches_schema (+0.4)
- Thresholds: >= 0.7 = accept, >= 0.4 = partial fallback, < 0.4 = full ladder

### HYB-09: Confidence Decision Routing
- >= 0.7: Use LLM extraction directly
- >= 0.4: Partial fallback (use some filters, heuristic for others)
- < 0.4: Trigger full fallback ladder

### HYB-10: Deterministic Override Layer
- Deterministic rules ALWAYS override LLM output
- Intent mismatch: current_intent != last_intent → force follow_up_type = "new"
- Created function: apply_overrides(extracted, state)

### HYB-11: Override Observability
- Log when overrides are applied for debugging
- Mark overrides_applied flag in state

### HYB-12: Conflict Resolution
- resolve_conflicts(new_filters, existing_filters) returns merged filters
- Same field → REPLACE (remove existing, add new)
- Different field → ADD (append new)
- Validate against FieldRegistry

### HYB-13: Field Validation in Conflict Resolution
- All fields must exist in semantic layer (FieldRegistry)
- All fields must match intent schema (domain compatibility)

### HYB-14: 6-Level Fallback Ladder
- execute_fallback_ladder(question, state, current_filters, failure_reason)
- Level 1: Retry LLM (stronger prompt)
- Level 2: Heuristic extraction (KNOWN_* constants)
- Level 3: Context recovery (infer from tokens)
- Level 4: Partial execution (run with partial filters)
- Level 5: Clarification (return ask_user prompt)
- Level 6: Full LLM fallback (generate SQL)

### HYB-15: Fallback Trigger Conditions
- confidence < 0.4: Start at level 3
- JSON parse failure: Start at level 2
- Invalid fields: Start at level 2

### HYB-16: Level 2 Heuristic Extraction
- Reuse patterns from param_extractor.py
- KNOWN_SKILLS, KNOWN_STATUS, KNOWN_DATES
- Map to FilterClause with appropriate operators

### HYB-17: Level 3 Context Recovery
- recover_from_context(question, last_filters)
- Tokenize question
- Match against KNOWN_PATTERNS
- Return inferred filters or empty list

### HYB-18: Level 5 Clarification
- Return structured clarification request when all levels fail
- User-friendly prompt asking for missing information

### HYB-19: Graceful Degradation
- System never crashes
- Always returns result or clarification request
- Logs fallback progression for observability

### HYB-20: Query Caching
- Cache key = hash(intent + filters + sort)
- get_cached_result(key) returns cached result or None
- cache_result(key, result) stores with TTL
- LRU eviction on max size (default 1000)

### HYB-21: Cache Integration
- Check cache after followup_detection, before llm_extraction
- Cache hit → skip LLM extraction entirely

### HYB-22: Observability Logging
- log_query_context(query, intent, filters, follow_up_type, confidence, final_sql, fallback_used)
- log_fallback_event(level, reason, extracted_filters)
- All logs in structured JSON format

### HYB-23: Semantic Integration Node
- get_field_hints(domain): Returns available fields from glossary
- normalize_filter_value(field, user_value): Maps user-friendly to DB values

### HYB-24: Glossary Integration with Extraction
- Use glossary hints to validate/map user terms
- "dev" → ResourceName, "skill" → PA_Skills.Name

### HYB-25: Dictionary Integration
- Use value_map for filter value normalization
- Load at startup (already done in Phase 7)

### HYB-26: End-to-End Hybrid Pipeline
- Full graph wiring: classify → followup_detection → llm_extraction → confidence_scoring → deterministic_override → conflict_resolution → plan_updater → run_domain_tool
- Fallback ladder at appropriate points
- Cache check before LLM extraction
- Observability at pipeline end

---

## Phase 9: Query Engine Refactor

### QE-01: QueryEngine Package and Core Types
- Create `backend/app/query_engine/` package with `__init__.py`
- Define `ExecutionStrategy` enum: `template`, `clarify`, `generate`, `reject`
- Define `PlanDecision` typed dict with: strategy, capability_id (optional), clarification_question (optional), rejection_reason (optional)
- Define `PlanFilter` model: `field: str`, `op: Literal["eq","in","lt","gt","between"]`, `values: list[str]` (sanitized, max 50), SQL injection guard
- Add docstrings and usage examples for all core types
- No runtime behavior change — types compile and serialize correctly

### QE-02: QueryPlan Contract
- Define canonical `QueryPlan` model in `backend/app/query_engine/types.py`
- Fields: domain, intent, task_type, filters (list[PlanFilter]), metrics, group_by, sort, limit, needs_clarification, ambiguity_reason, novel_requirements, confidence
- `QueryPlan` outputs structured plan, NOT SQL
- `from_untrusted_dict()` classmethod for safe deserialization
- `to_api_dict()` for serialized output
- `schema_version: Literal[2]` (version bump from Phase 7's version=1)
- Tests validate serialization roundtrip and schema shape

### QE-03: ConversationState Contract
- Define canonical `ConversationState` model in `backend/app/query_engine/state.py`
- Fields: thread_id, user_id, connection_id, messages, active_topic, active_domain, active_plan, active_filters, last_result_meta, clarification_pending, clarification_question, execution_strategy, confidence, schema_version
- Follow-up refinement mutates active_plan; topic switch replaces active_plan
- Clarification pauses execution until answered
- Raw SQL is NOT primary conversation memory — plan and filters are primary
- Tests validate state mutation rules (refine, new_topic, clarify)

### QE-04: PlanDecision and Strategy Enum
- Define `PlanDecision` and `ExecutionStrategy` with deterministic routing contract
- Strategy decision order: reject (out of scope) → clarify (ambiguous) → template (fully covered by catalog) → generate (fallback)
- One route decision per query — no duplicated routing logic outside selector
- Selector behavior testable without LLM

### QE-05: Query Engine Configuration Cleanup
- Refactor scattered query configuration in `backend/app/config.py`
- Add startup validation for required query engine settings (confidence thresholds, retry limits, row limits, timeout defaults)
- Replace legacy feature flags (`USE_QUERY_PLAN_COMPILER`, `USE_GROQ_EXTRACTOR`, `USE_HYBRID_MODE`) with new unified query engine config model
- Mark legacy flags as migration artifacts — remove before Phase 9 completion
- App boots cleanly with new config; no long-lived routing flags in final architecture

### QE-06: Capability Catalog Model
- Create `backend/app/query_engine/catalog/models.py` with `CapabilityEntry` model
- Each entry defines: intent_id, domain, business_meaning, sql_template, supported_filters, supported_grouping, supported_metrics, unsupported_operations, follow_up_behavior, result_shape, parameter_binding_rules
- Structured metadata replaces brittle FAQ-matching intent catalog
- All capabilities declare what filters they support and what operations they do NOT support

### QE-07: Capability Catalog Registry
- Create `backend/app/query_engine/catalog/registry.py` with `CapabilityRegistry`
- Register all capabilities by domain and intent
- Validate capability completeness at startup (no missing required fields)
- Lookup methods: by_intent_id, by_domain, match_by_plan (for Capability Matcher)
- Startup validation raises error if any domain-intent pair has incomplete metadata

### QE-08: Capability Catalog Extraction
- Extract all current trusted SQL from domain agents (resource, project, client, timesheet, user_self) into structured capability entries
- No business-critical predefined SQL remains only inside old domain agent classes
- Domain-specific catalog files: `catalog/resource.py`, `catalog/project.py`, `catalog/client.py`, `catalog/timesheet.py`, `catalog/user_self.py`
- Capability extraction includes parameter binding rules translated from current `_run_intent()` methods
- Validation tests confirm catalog entries cover all 24+ active intents

### QE-09: Planner Implementation
- Create `backend/app/query_engine/planner.py` with `QueryPlanner` service
- Planner outputs structured `QueryPlan` — never SQL directly
- Refactor current Groq extractor logic into planner-only behavior
- Planner classifies domain, intent, task_type, filters, metrics, grouping, sort, limit
- Explicitly surfaces ambiguity (needs_clarification=True, ambiguity_reason) and novelty (novel_requirements) flags
- Planner test suite with: common queries, ambiguous queries, unsupported queries, follow-up refinement queries
- No planner branch executes SQL directly

### QE-10: Capability Matcher
- Create `backend/app/query_engine/matcher.py` with `CapabilityMatcher`
- Compare `QueryPlan` against capability catalog; output: full_match, partial_match, no_match
- Match scoring considers: filter coverage, grouping support, metric support, parameter compatibility
- Produce mismatch reasons on partial/no match (available to Strategy Selector)
- Common supported asks map to full catalog matches; unsupported asks are not forced into bad templates
- Unit tests for each supported intent family

### QE-11: Strategy Selector
- Create `backend/app/query_engine/selector.py` with `StrategySelector`
- Deterministic decision order: reject if out of scope → clarify if ambiguous → template if fully covered by catalog → generate otherwise
- One route decision per query — no parallel routing logic outside selector
- Add metrics hooks for route counts (template, generate, clarify, reject) and latency
- Testable without LLM invocation

### QE-12: Template Executor
- Create `backend/app/query_engine/executors/template_executor.py`
- Execute trusted predefined query capabilities from the Capability Catalog
- Deterministic, fast, parameterized, scope-aware
- Parameter binding helpers (IN clause construction, NULL handling, type coercion)
- Inject deterministic RBAC scope (user-scoped filters, row limits)
- Execute through existing connector infrastructure
- Return normalized execution result metadata
- Latency measurably lower than generation path

### QE-13: Generation Executor
- Create `backend/app/query_engine/executors/generation_executor.py`
- Handle only requests that cannot be satisfied by the capability catalog
- Explicit fallback strategy — invoked only when Strategy Selector chooses `generate`
- Move heavy semantic context building (glossary, schema linking, knowledge retrieval) into this path only
- Reuse existing retrieval, glossary, and schema-linking services where useful
- Validate and scope generated SQL through shared Execution Guard layer
- Common catalog-supported traffic never uses this path

### QE-14: Execution Guardrail Layer
- Create `backend/app/query_engine/guards.py` and `backend/app/query_engine/validator.py`
- Centralize: RBAC, row limits, timeout enforcement, read-only transaction mode, SQL validation, audit metadata
- Both template and generation paths pass through the same guard layer
- Prompt-only RBAC dependence removed — scope filters are deterministic
- SQL validation uses blocklist from `app/utils/sql_sanitizer.py` (no DDL, DML, admin commands)
- Timeout: configurable per-connection, enforced at execution level
- Audit metadata: strategy used, capability_id, execution_time_ms, row_count

### QE-15: Conversation State System
- Create `backend/app/query_engine/state.py` with `ConversationState` and reducers
- Create `backend/app/query_engine/checkpointer.py` for Postgres-backed thread persistence via LangGraph checkpointer
- Create `backend/app/query_engine/reducers.py` for messages, active_filters, active_plan mutations
- Create `backend/app/query_engine/conversation_resolver.py`: resolve conversational context, detect topic switches, resolve pronouns/entity references, preserve active filter state during refinement
- Create `backend/app/query_engine/conversation_graph.py`: thin LangGraph workflow for thread lifecycle, clarification loops, checkpointing
- State survives app restarts; behavior consistent across horizontal instances
- Follow-up questions mutate active plan deterministically; topic switch resets plan cleanly

### QE-16: Session Ownership and Security
- Add `user_id` to `chat_sessions` model (Alembic migration)
- Scope session endpoints by owner (user can only list/access own sessions)
- Scope thread state by session and user
- No cross-user session leakage
- Thread identity is durable and user-scoped
- Backfill or handle existing session ownership model safely; old sessions not silently orphaned

### QE-17: Query Service Rewrite
- Rewrite `backend/app/services/query_service.py` as a clean orchestrator over the new `query_engine` package
- Replace direct LangGraph graph invocation with query engine service orchestration
- Remove ad hoc route branching from service layer
- Remove topic-switch heuristics from service layer (moved to Conversation Resolver)
- Normalize result assembly (consistent response shape regardless of strategy)
- `query_service.py` becomes significantly smaller — orchestration logic delegates to `query_engine`

### QE-18: API Layer Update
- Refactor `backend/app/api/v1/endpoints/query.py` to use new query engine service
- API is thin and stable — endpoint delegates entirely to query service
- Response includes metadata: strategy used, capability_id, clarification_status, thread_state_version
- Stream endpoint no longer uses fake timer stages
- Response contract consistent with new engine output

### QE-19: Retrieval Split
- Create `backend/app/query_engine/retrieval/lightweight.py`: entity/value resolution, glossary hints — used by template path
- Create `backend/app/query_engine/retrieval/heavyweight.py`: full semantic context assembly (schema linking, knowledge chunks, glossary enrichment) — used only by generation path
- Template path does not pay heavy retrieval cost (no LLM context assembly)
- Generation path retains full semantic support
- Both modules reuse existing services (`embedding_service`, `schema_linker`, `glossary_resolver`, `knowledge_service`)

### QE-20: Observability
- Create `backend/app/query_engine/metrics.py`
- Track: planner latency, catalog match rate, template execution rate, generation execution rate, clarification rate, reject rate
- Track: execution success/failure by strategy, p50/p95 latency by strategy, token cost on generation path
- All core pipeline stages observable via structured logging
- Production behavior explainable via metric output
- Bottlenecks identifiable from metric data

### QE-21: Legacy Retirement
- Remove old graph routing stack: `backend/app/llm/graph/graph.py`, `backend/app/llm/graph/state.py`
- Remove `backend/app/llm/graph/nodes/llm_groq_extractor.py`, `backend/app/llm/graph/nodes/llm_fallback.py`, `backend/app/llm/graph/nodes/plan_updater.py`
- Remove `backend/app/llm/graph/domains/base_domain.py`, `backend/app/llm/graph/domains/registry.py`
- Remove large portions of `backend/app/llm/graph/nodes/sql_compiler.py`
- Remove domain-specific agent SQL implementations (migrated into catalog capabilities)
- Remove legacy feature flags (`USE_QUERY_PLAN_COMPILER`, `USE_GROQ_EXTRACTOR`, `USE_HYBRID_MODE`)
- No parallel architecture remains — all traffic uses query engine pipeline
- Codebase easier to navigate and maintain

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| LG-01 | Phase 5 | Complete |
| LG-02 | Phase 5 | Complete |
| LG-03 | Phase 5 | Complete |
| LG-04 | Phase 5 | Complete |
| LG-05 | Phase 5 | Complete |
| LG-06 | Phase 5 | Complete |
| LG-07 | Phase 5 | Complete |
| LG-08 | Phase 5 | Complete |
| LG-09 | Phase 5 | Complete |
| LG-10 | Phase 5 | Complete |
| LG-11 | Phase 5 | Complete |
| LG-12 | Phase 5 | Complete |
| LG-13 | Phase 5 | Complete |
| LG-14 | Phase 5 | Complete |
| LG-15 | Phase 5 | Complete |
| LG-16 | Phase 5 | Complete |
| QP-01 | Phase 7 | Planned |
| QP-02 | Phase 7 | Planned |
| QP-03 | Phase 7 | Planned |
| QP-04 | Phase 7 | Planned |
| HYB-01 | Phase 8 | Planned |
| HYB-02 | Phase 8 | Planned |
| HYB-03 | Phase 8 | Planned |
| HYB-04 | Phase 8 | Planned |
| HYB-05 | Phase 8 | Planned |
| HYB-06 | Phase 8 | Planned |
| HYB-07 | Phase 8 | Planned |
| HYB-08 | Phase 8 | Planned |
| HYB-09 | Phase 8 | Planned |
| HYB-10 | Phase 8 | Planned |
| HYB-11 | Phase 8 | Planned |
| HYB-12 | Phase 8 | Planned |
| HYB-13 | Phase 8 | Planned |
| HYB-14 | Phase 8 | Planned |
| HYB-15 | Phase 8 | Planned |
| HYB-16 | Phase 8 | Planned |
| HYB-17 | Phase 8 | Planned |
| HYB-18 | Phase 8 | Planned |
| HYB-19 | Phase 8 | Planned |
| HYB-20 | Phase 8 | Planned |
| HYB-21 | Phase 8 | Planned |
| HYB-22 | Phase 8 | Planned |
| HYB-23 | Phase 8 | Planned |
| HYB-24 | Phase 8 | Planned |
| HYB-25 | Phase 8 | Planned |
| HYB-26 | Phase 8 | Planned |
| QE-01 | Phase 9 | Planned |
| QE-02 | Phase 9 | Planned |
| QE-03 | Phase 9 | Planned |
| QE-04 | Phase 9 | Planned |
| QE-05 | Phase 9 | Planned |
| QE-06 | Phase 9 | Planned |
| QE-07 | Phase 9 | Planned |
| QE-08 | Phase 9 | Planned |
| QE-09 | Phase 9 | Planned |
| QE-10 | Phase 9 | Planned |
| QE-11 | Phase 9 | Planned |
| QE-12 | Phase 9 | Planned |
| QE-13 | Phase 9 | Planned |
| QE-14 | Phase 9 | Planned |
| QE-15 | Phase 9 | Planned |
| QE-16 | Phase 9 | Planned |
| QE-17 | Phase 9 | Planned |
| QE-18 | Phase 9 | Planned |
| QE-19 | Phase 9 | Planned |
| QE-20 | Phase 9 | Planned |
| QE-21 | Phase 9 | Planned |
