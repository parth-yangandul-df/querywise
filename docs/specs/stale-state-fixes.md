# Stale State Bug Fixes — Spec

## Problem

LangGraph state is **additive**: a node return dict only updates keys it explicitly includes. Any key NOT in the return dict persists unchanged across cycles. This caused infinite loops and incorrect routing when nodes failed to clear stale flags from previous cycles.

## Root Cause Pattern

```
Node A returns {"action": "retry"}          → state.action = "retry"
Node A returns {"generated_sql": "..."}     → state.action STILL "retry"!
Router sees stale action                    → routes back to Node A → infinite loop
```

## Fixes Applied

### compose_sql (primary infinite loop source)

| Field | Before (stale) | After |
|-------|----------------|-------|
| `action` | Not set on success → stale `"no_sql_retry"` | Set to `"query"` on success |
| `previous_attempts` | Overwritten to `[sql]` (len=1) → hard limit never fires | Appended to existing list |
| `retry_count` | Reset to `0` on success | Preserved from state |
| `validation_issues` | Not cleared → stale issues | Cleared to `[]` on success |
| `needs_context_rebuild` | Not cleared → stale rebuild | Cleared to `False` on success |
| `force_include_tables` | Not cleared → stale forced tables | Cleared to `[]` on success |
| `generated_sql` | Not cleared on retry → stale SQL | Set to `None` on retry |

### handle_error

| Field | Before (stale) | After |
|-------|----------------|-------|
| `action` | Not set on retry → stale `"clarification"` routes to write_history | Set to `"query"` on retry |
| `validation_issues` | Not cleared | Cleared to `[]` on retry |
| `needs_context_rebuild` | Not cleared | Cleared to `False` on retry |
| `force_include_tables` | Not cleared | Cleared to `[]` on retry |

### validate_sql

| Field | Before (stale) | After |
|-------|----------------|-------|
| `needs_context_rebuild` | Not cleared on valid → stale rebuild | Cleared to `False` on valid |
| `force_include_tables` | Not cleared on valid | Cleared to `[]` on valid |

### rebuild_context

| Field | Before (stale) | After |
|-------|----------------|-------|
| `force_include_tables` | Not cleared → repeated rebuilds | Cleared to `[]` on success |
| `validation_issues` | Kept stale → re-route to handle_error | Cleared to `[]` on success |

### similarity_check

| Field | Before (stale) | After |
|-------|----------------|-------|
| `similarity_hint_sql` | Not cleared on no-match → stale hint injected into composer | Set to `None` on all no-match paths |

## Verification Checklist

For each node that returns a dict, verify:
1. Every routing-critical field (`action`, `_target_node`) is explicitly set
2. Every flag field (`needs_context_rebuild`, `similarity_shortcut`) is cleared when not applicable
3. Every list field (`validation_issues`, `force_include_tables`, `previous_attempts`) is cleared/reset when not applicable
4. Every "hint" field (`similarity_hint_sql`) is cleared to `None` when not applicable
5. Counter fields (`retry_count`, `compose_retry_count`) are never reset to 0 on success

## Nodes Verified Safe (no stale issues)

- `resolve_turn` — always sets `action` explicitly
- `handle_follow_up` — always sets `action` explicitly
- `execute_sql` — clears `error: None` on success
- `build_context_node` — overwrites `prompt_context`, `schema_tables` fully
- `answer_from_state` — terminal path to `write_history`
- `write_history` — terminal node

## Remaining Risks

None identified. All nodes that participate in retry/correction cycles have been audited and fixed.
