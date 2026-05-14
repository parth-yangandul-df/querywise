"""Shared utilities for LLM response parsing."""

import json
import re


def repair_json(text: str) -> str:
    """Best-effort cleanup of malformed JSON from LLM responses.

    Handles common issues from smaller/chat models:
    - Preamble text before the JSON (e.g. "Here is the JSON response:")
    - Markdown code fences wrapping JSON (```json ... ```)
    - Trailing text/notes after the closing fence
    - Python-style True/False/None instead of true/false/null
    - Trailing commas before } or ]

    Returns the repaired string. Callers should still catch json.JSONDecodeError
    because repair is best-effort and may not fix all malformed inputs.
    """
    s = text.strip()

    # 1. Extract content from a markdown code fence, anywhere in the string.
    #    Handles preamble ("Here is the JSON:") and trailing notes.
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", s, re.DOTALL)
    if fence_match:
        s = fence_match.group(1).strip()
    else:
        # 2. No fence — try to extract a bare JSON object or array.
        #    Use a non-greedy search anchored to the first { or [ so we don't
        #    swallow truncated JSON that has an unrelated } later in the string.
        #    Strategy: find first { or [, then walk forward to find its closing
        #    bracket at the correct nesting depth.
        first_brace = -1
        open_char: str | None = None
        close_char: str | None = None
        for i, ch in enumerate(s):
            if ch in ("{", "["):
                first_brace = i
                open_char = ch
                close_char = "}" if ch == "{" else "]"
                break

        if first_brace >= 0 and open_char and close_char:
            depth = 0
            in_string = False
            escape_next = False
            end_pos = -1
            for i in range(first_brace, len(s)):
                ch = s[i]
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\" and in_string:
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == open_char:
                    depth += 1
                elif ch == close_char:
                    depth -= 1
                    if depth == 0:
                        end_pos = i
                        break

            if end_pos >= 0:
                s = s[first_brace : end_pos + 1].strip()

    # Fix Python-style booleans/None (only outside quoted strings)
    # Simple approach: replace whole-word occurrences
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    s = re.sub(r"\bNone\b", "null", s)

    # Remove trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # Final validation: if the result still isn't valid JSON, return an empty
    # object so callers get a consistent JSONDecodeError from json.loads("{}").
    # This prevents silently returning a half-repaired string that json.loads
    # would accept as a truncated but "valid" partial string.
    try:
        json.loads(s)
    except (json.JSONDecodeError, ValueError):
        # Return empty object — callers handle json.JSONDecodeError themselves
        return "{}"

    return s
