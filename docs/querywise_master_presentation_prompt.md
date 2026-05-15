# QueryWise Master Presentation Prompt

## Purpose
This document provides a master prompt for generating a comprehensive presentation on QueryWise, focusing on its agentic AI architecture and how it differs from traditional systems.

---

**Prompt:**

You are an expert technical presenter. Create a visually engaging, detailed presentation that explains the architecture and unique agentic AI approach of QueryWise, a text-to-SQL application with a semantic metadata layer.

### Cover the following topics:

1. **What is QueryWise?**
   - Natural language to SQL pipeline
   - Semantic metadata layer (glossary, metrics, dictionaries, knowledge base)
   - Multi-turn conversation context
   - Multi-database support (PostgreSQL, SQL Server)
   - Provider-agnostic LLM (Anthropic, OpenAI, Ollama, OpenRouter, Groq)

2. **Traditional Systems vs. QueryWise**
   - Traditional: Rule-based, static SQL templates, hardcoded business logic, limited adaptability, no semantic context, no agent orchestration.
   - QueryWise: Agentic AI pipeline, dynamic context assembly, semantic retrieval, LLM-driven SQL generation, multi-agent error handling, RBAC-aware, graceful fallback, and audit trail.

3. **Agentic AI Architecture**
   - LangGraph-powered stateful pipeline: Each node is an agent (composer, validator, error handler, interpreter, etc.)
   - Multi-turn flow: load history → intent resolution → context building → similarity check → SQL composition → validation → error handling → execution → interpretation
   - Agents collaborate, retry, and escalate as needed (e.g., error handler agent corrects SQL, validator agent checks schema, etc.)
   - RBAC and scope constraints injected at prompt level for user-specific queries

4. **Semantic Layer**
   - Hybrid context builder: combines embedding similarity, keyword matching, FK expansion, glossary/metric/dictionary/knowledge retrieval
   - All business logic and domain knowledge live in metadata, not code
   - Graceful degradation: falls back to keyword-only if embeddings unavailable

5. **Key Differentiators**
   - No business logic in code: all domain knowledge is metadata-driven
   - Hybrid retrieval (vector + keyword + FK expansion)
   - Agentic, multi-agent orchestration (not monolithic LLM calls)
   - Full audit trail and idempotent setup
   - Multi-provider, multi-database, multi-turn, and RBAC-aware

6. **Visuals to Include**
   - LangGraph pipeline diagram (showing agent nodes and flow)
   - Semantic layer context assembly flow
   - Comparison table: Traditional vs. QueryWise (agentic, semantic, multi-turn, RBAC, etc.)

7. **Summary**
   - How QueryWise’s agentic AI and semantic layer enable more robust, adaptable, and explainable NL-to-SQL than traditional systems.

---

Use this prompt to guide an LLM or human presenter in generating a detailed, architecture-focused presentation that highlights QueryWise’s agentic AI innovations and contrasts them with traditional approaches.