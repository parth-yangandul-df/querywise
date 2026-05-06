# QueryWise Chatbot Test Questions

A structured test bank for manually validating chatbot accuracy, SQL correctness, and conversation quality.

---

## Category 1: Basic Intent Resolution

Test that single-turn queries resolve the correct intent and return valid SQL.

### Resources

| # | Question | Expected Intent | Pass Criteria |
|---|----------|----------------|---------------|
| R1 | "Show me all active resources" | `active_resources` | SQL filters `IsActive=1` AND `statusid=8` |
| R2 | "Who is on the bench right now?" | `benched_resources` | SQL targets bench project (ProjectId=119) |
| R3 | "List all Python developers" | `resource_by_skill` | SQL does OR search across skill columns with 'Python' |
| R4 | "Which resources are available?" | `resource_availability` | Returns unassigned active resources |
| R5 | "Show me John Smith's project assignments" | `resource_project_assignments` | Filters by resource name = 'John Smith' |
| R6 | "What skills does Jane Doe have?" | `resource_skills_list` | Filters by resource name = 'Jane Doe' |
| R7 | "What is my current allocation?" | `my_allocation` | SQL uses `resource_id` from logged-in user context |
| R8 | "Show my skills" | `my_skills` | SQL filters by `resource_id` of current user |

### Clients

| # | Question | Expected Intent | Pass Criteria |
|---|----------|----------------|---------------|
| C1 | "Show me all active clients" | `active_clients` | SQL filters `IsActive=1 AND StatusId=2` |
| C2 | "Show projects for client Acme Corp" | `client_projects` | SQL filters by client name 'Acme Corp' |
| C3 | "What is the status of TechCorp client?" | `client_status` | Returns status fields for 'TechCorp' |

### Projects

| # | Question | Expected Intent | Pass Criteria |
|---|----------|----------------|---------------|
| P1 | "List all active projects" | `active_projects` | SQL filters `IsActive=1 AND ProjectStatusId=4` |
| P2 | "Show projects for Acme Corp" | `project_by_client` | SQL joins/filters by client = 'Acme Corp' |
| P3 | "What is the budget for Project Alpha?" | `project_budget` | Returns budget columns for 'Project Alpha' |
| P4 | "Who is working on Project Beta?" | `project_resources` | Returns resources assigned to 'Project Beta' |
| P5 | "What are the start and end dates for Project Gamma?" | `project_timeline` | Returns `StartDate`, `EndDate` for 'Project Gamma' |
| P6 | "Which projects are overdue?" | `overdue_projects` | SQL has `EndDate < GETDATE()` or equivalent |

### Self-Service

| # | Question | Expected Intent | Pass Criteria |
|---|----------|----------------|---------------|
| S1 | "Show my projects" | `my_projects` | SQL uses current user's resource_id |
| S2 | "What's my utilization rate?" | `my_utilization` | Returns utilization metrics for current user |

---

## Category 2: Multi-Turn Context Awareness

Test that conversation context carries forward correctly between turns.

### Refinement (Adding Constraints)

| # | Turn 1 | Turn 2 | Expected Behavior |
|---|--------|--------|-------------------|
| MT1 | "Show me active projects" | "Now filter by budget over 50000" | Budget filter applied to previous result set |
| MT2 | "List all Python developers" | "Only show senior level" | Adds seniority/experience filter |
| MT3 | "Show active clients" | "Filter to those in Bangalore" | Adds city/location filter |
| MT4 | "Show me benched resources" | "Only those with Java skills" | Applies skill filter on bench results |
| MT5 | "List all projects" | "Sort by end date" | Re-orders by end date |

### Topic Switch (Context Clear)

| # | Turn 1 | Turn 2 | Expected Behavior |
|---|--------|--------|-------------------|
| MT6 | "Show me benched resources" | "Actually, show all active clients instead" | `topic_switch_detected=true`; fresh query for clients |
| MT7 | "Projects for client Acme" | "Forget that, what are overdue projects?" | Context cleared; returns overdue projects |
| MT8 | "Show my skills" | "Now show me all Python developers" | Fresh intent, ignores self-service context |

### Chained Refinements (3+ turns)

| # | Turn 1 | Turn 2 | Turn 3 | Expected Behavior |
|---|--------|--------|--------|-------------------|
| MT9 | "Show active clients" | "In Bangalore" | "With more than 5 projects" | Stacks both filters correctly |
| MT10 | "List resources" | "Only those with Python skills" | "Who are also on bench" | Produces SQL combining skill + bench filters |

### Follow-up Clarification

| # | Turn 1 | Turn 2 | Expected Behavior |
|---|--------|--------|-------------------|
| MT11 | "Show me John's projects" | "How many does he have?" | Returns count of John's projects |
| MT12 | "Active projects" | "Which ones started this year?" | Adds `StartDate >= YEAR(GETDATE())` filter |

---

## Category 3: Analytical / LLM Fallback Queries

Test queries that cannot be handled by direct intent matching and require LLM reasoning.

| # | Question | Expected Behavior |
|---|----------|-------------------|
| A1 | "Which project has the highest resource utilization?" | LLM generates aggregation query; returns ranked results |
| A2 | "Compare headcount across all active projects" | LLM generates GROUP BY query; returns project-wise counts |
| A3 | "What percentage of resources are currently unallocated?" | LLM calculates ratio; returns numeric answer |
| A4 | "Which client has the most ongoing projects?" | LLM generates aggregation with ORDER BY |
| A5 | "What is the average project budget this year?" | LLM generates AVG with year filter |
| A6 | "How many projects started in the last 30 days?" | LLM handles relative date arithmetic |
| A7 | "Show me the top 5 most skilled resources" | LLM handles skill-count aggregation |
| A8 | "Which projects are at risk (near deadline, low completion)?" | LLM infers risk criteria from schema |

---

## Category 4: Ambiguity and Clarification

Test how the system handles ambiguous or incomplete queries.

| # | Question | Expected Behavior |
|---|----------|-------------------|
| AM1 | "Show me John" | Returns results for any entity named John, or asks to clarify domain |
| AM2 | "Get me the numbers" | Returns clarification request or general metrics |
| AM3 | "What's the status?" | Asks which entity (project/client/resource) |
| AM4 | "How many are there?" | Asks clarification or defaults to most common entity |
| AM5 | "Show projects" | Returns all projects (no filter); not ambiguous — valid broad query |

---

## Category 5: Edge Cases & Robustness

Test robustness around input formatting, special characters, and boundary conditions.

| # | Question | Expected Behavior |
|---|----------|-------------------|
| E1 | "SHOW ME ACTIVE RESOURCES" | Case-insensitive handling; same result as R1 |
| E2 | "shwo me acitve resoruces" (typos) | Intent still matched; fuzzy/semantic matching works |
| E3 | "Show me active resources!" | Punctuation stripped; handled correctly |
| E4 | "Search for client named 'Test & Co'" | Special characters escaped safely in SQL |
| E5 | "Show me projects with budget of -1000" | Graceful empty result or validation message |
| E6 | "   " (whitespace only) | API rejects with 422 (min_length=1 validation) |
| E7 | Long query (500+ chars) | Handled within max_length=1000; no crash |
| E8 | "Show me all resources AND clients AND projects AND budgets AND timelines" | Reasonable response or asks user to split query |

---

## Category 6: Security / SQL Injection Prevention

Test that the SQL sanitizer blocks malicious inputs.

| # | Question | Expected Behavior |
|---|----------|-------------------|
| SEC1 | "Show resources; DROP TABLE resources --" | Blocked; sanitizer detects DDL/injection |
| SEC2 | "List projects WHERE 1=1; DELETE FROM projects" | Blocked; DML blocked |
| SEC3 | "' OR '1'='1" | No injection; parameterized queries used |
| SEC4 | "Show me resources UNION SELECT password FROM users" | Blocked or returned empty with error |

---

## Category 7: Answer Quality

Test that the natural language explanation (interpretation) of results is correct and helpful.

| # | Question | What to Verify |
|---|----------|----------------|
| AQ1 | "How many active clients do we have?" | `summary` field contains the count as a sentence |
| AQ2 | "Show me Python developers" | Explanation mentions filtering by Python skill |
| AQ3 | "What are overdue projects?" | Explanation clarifies the date condition used |
| AQ4 | "Show me bench resources" | `suggested_followups` contains relevant next questions |
| AQ5 | Any result with 0 rows | `explanation` or `summary` communicates empty result clearly |

---

## Manual Testing Checklist

For each test run, verify the following response fields:

- [ ] `generated_sql` — Correct table names, correct filters
- [ ] `explanation` — Accurate natural language description of what was queried
- [ ] `columns` — Expected columns are returned
- [ ] `rows` — Data looks correct (spot-check against DB)
- [ ] `row_count` — Matches actual `len(rows)`
- [ ] `summary` — Present and meaningful
- [ ] `suggested_followups` — Contextually relevant (3 suggestions)
- [ ] `turn_context.intent` — Correct intent name
- [ ] `turn_context.domain` — Correct domain (resource/client/project/user_self)
- [ ] `topic_switch_detected` — Accurate flag on context switches
- [ ] `llm_provider` / `llm_model` — Reflects actual provider used
