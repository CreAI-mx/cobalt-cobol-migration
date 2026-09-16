---
name: cobol-business-logic-extraction
description: Phase 2 of COBOL-to-C# migration. Translates structural analysis into business language — user stories, business rules, glossary. This is agentic (LLM), not deterministic — the only phase before this point that isn't pure parsing. Triggers after cobol-structural-analysis for a file.
---

# COBOL Business Logic Extraction

Purpose: answer "what does this program do for the business", not "what does this syntax mean".

## Input
`cobol_analyses` row for one file (paragraphs_json is the primary source).

## Steps (agentic — LLM required here)
1. Read paragraph names + control flow from `cobol_analyses`.
2. Per paragraph, infer intent in plain business language (e.g. "DEBIT-ACCOUNT: reject the debit if it would take balance negative").
3. Extract explicit business rules as testable assertions (e.g. "balance must never go below zero on debit").
4. Write `business_logic_extracts` row: `user_stories_json`, `business_rules_json`.

## Guardrail
Every business rule extracted here MUST be traceable back to a specific paragraph/line in the source — no rule invented without a source anchor. This output feeds test generation (Phase 5); an untraceable rule produces an unverifiable test.

## Output language (standing rule, enforced in llm.py's prompt too — repeated here on purpose)
English. Dense, factual, no filler, no hedging, no marketing adjectives — regardless
of the source COBOL's own comment language. This applies to every generated field:
user_stories, business_rules, suggested_component_name.

## Output
`business_logic_extracts` row per file.

## Feeds
`cobol-to-csharp-conversion` (business rules justify *why* the generated code branches the way it does), `csharp-test-generation` (business rules become test case titles).
