# Detector Coverage Report

Generated: 2026-10-13T20:38:09.760495Z

## Coverage Summary

| Path | Count | Percentage |
|------|-------|------------|
| (a) Live probe with key | 8 | 80.0% |
| (b) Live probe no key | 0 | 0.0% |
| (c) SIMULATED only | 2 | 20.0% |
| BLOCKED | 0 | 0.0% |
| **Total** | **10** | **100%** |

**Coverage (a+b): 80.0%** FAIL (< 95%)

## Per-Entry Scorecard

| ID | Type | Path | Dialect | Auth | Models | Capabilities | Latency | Errors |
|----|------|------|---------|------|--------|--------------|---------|--------|
| groq | keyed | a | openai-chat | /models | 2 | 2 models | 1463ms |  |
| cerebras | keyed | a | openai-chat | /models | 2 | 2 models | 4700ms |  |
| mistral | keyed | a | openai-chat | /models | 2 | 2 models | 7269ms |  |
| cohere | keyed | a | openai-chat | /models | 2 | 2 models | 2640ms |  |
| openrouter | keyed | a | openai-chat | none | 3 | 3 models | 22320ms |  |
| gemini | keyed | a | openai-chat | /models | 1 | 1 models | 2569ms |  |
| pollinations | keyed | a | openai-chat | /models | 1 | 1 models | 1802ms |  |
| aihorde | free | c | unknown | ? | 0 |  | 0ms | no working /models endpoint [SIMULATED] |
| anyapi | keyed | a | openai-chat | /models | 1 | 1 models | 2396ms |  |
| xai | keyed | c | openai-chat (assumed) | bearer (assumed) | 2 |  | 0ms | SIMULATED, unverified - no key available, no public access [SIMULATED] |

## BLOCKED Entries

*None*

## Fuzz Results

| Provider | Test | Result |
|----------|------|--------|
| groq | nonstandard_path | HTTP 403 |
| groq | nonstandard_path | HTTP 403 |
| groq | nonstandard_path | HTTP 403 |
| groq | nonstandard_path | HTTP 403 |
| cerebras | nonstandard_path | HTTP 403 |
| cerebras | nonstandard_path | HTTP 403 |
| cerebras | nonstandard_path | HTTP 403 |
| cerebras | nonstandard_path | HTTP 403 |
| groq | ndjson_streaming | Error: HTTP Error 403: Forbidden |
| cerebras | ndjson_streaming | Error: HTTP Error 403: Forbidden |
| groq | anthropic_tool_format | HTTP 403 |
| cerebras | anthropic_tool_format | HTTP 403 |
| openrouter | no_list_endpoint | provider has no /models endpoint - requires candidate probing |
| aihorde | no_list_endpoint | provider has no /models endpoint - requires candidate probing |
| xai | no_list_endpoint | provider has no /models endpoint - requires candidate probing |

## Holdout Test (20 Invented Providers)

| Provider | Base URL | Inferred Dialect | Inferred Auth | Notes |
|----------|----------|------------------|---------------|-------|
| holdout-nova | https://api.nova.ai/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-orion | https://orion.com/openai/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-atlas | https://llm.atlas.cloud/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-nexus | https://inference.nexus.dev/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-zenith | https://zenith.api.gpu/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-apex | https://api.apex.ai/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-vertex | https://vertex.com/openai/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-horizon | https://llm.horizon.cloud/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-meridian | https://inference.meridian.dev/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-equinox | https://equinox.api.gpu/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-solstice | https://api.solstice.ai/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-eclipse | https://eclipse.com/openai/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-nova | https://llm.nova.cloud/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-lunar | https://inference.lunar.dev/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-solar | https://solar.api.gpu/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-stellar | https://api.stellar.ai/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-cosmic | https://cosmic.com/openai/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-galactic | https://llm.galactic.cloud/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-nebula | https://inference.nebula.dev/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |
| holdout-quasar | https://quasar.api.gpu/v1 | openai-chat | bearer | inferred from URL pattern only - no live calls made |

---
*Report generated by detect_all.py*