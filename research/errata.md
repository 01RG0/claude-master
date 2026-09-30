# Research Errata & Authoritative System Amendments

This document records mandatory corrections, amendments, and operational constraints applied to the initial research findings in `research/` as mandated by the Project Master Specification.

---

## 1. Gateway Deployment: Primary Execution Path Interception
- **Research Claim**: `architecture-fit.md` depicted the router primarily serving auxiliary and reflection requests.
- **Correction**: To fulfill the **100% Free / Zero Claude Model Dependency** mission, our Go gateway (`gateway/`) MUST sit directly in Claude Code's primary execution path. Claude Code will be launched with `ANTHROPIC_BASE_URL=http://localhost:8080/v1` (or local port). The gateway translates all incoming `/v1/messages` requests (streaming events, tool definitions, thoughts, and sub-agents) to free upstream providers (Cerebras, Groq, Mistral, Gemini Public).
- **Verification Rule**: Proven via live integration tests capturing real Claude Code request structures.

---

## 2. Claude Code Hook API Grounding
- **Research Claim**: Quoted hook event names and payload schemas based on preview versions.
- **Correction**: All hook events, schemas, stdin/stdout formats, exit code conventions, and context injection mechanisms must be validated against the live `claude` runtime (v2.1.263) and official documentation before coding. Verified schemas will be recorded in `contracts/hook-payloads.md` and `docs/claude-code-facts.md`.

---

## 3. Drex Runtime Gating: Hosted Decision Model Protocol
- **Research Claim**: Latency referenced as "<15 ms" and "11.2 ms measured".
- **Correction**: Drex is a remote hosted API, not an in-process check. Network roundtrips vary by geographic region.
  - **Fail-Open Policy**: Any Drex timeout (>150ms default) or HTTP failure MUST fail-open to avoid blocking developer terminal actions.
  - **Redaction & Privacy**: Never transmit secrets, `.env` values, or entire source files to Drex. Transmit only abstracted/redacted command descriptors.
  - **Caching**: Identical commands/states must be cached locally in-memory to reduce latency to ~0ms.

---

## 4. Privacy-Aware Model Routing
- **Research Claim**: All free providers treated equally under bandit load balancing.
- **Correction**: Upstream providers have drastically different data retention and privacy policies.
  - **Google Gemini Free Tier**: Marked `public-data-only`. Google AI Studio terms state free-tier queries are subject to human review and model training. Proprietary code, git diffs, and project secrets MUST NEVER be dispatched to Gemini free tier.
  - **Zero-Retention Providers** (e.g. Groq, Cerebras Tier-0): Eligible for internal code refactoring and project diff analysis.
  - Enforced dynamically per request inside `gateway/`.

---

## 5. Anti-Abuse & TOS Compliance
- **Research Claim**: Mentioned multi-account key pools.
- **Correction**: Creating multiple accounts per person/organization to evade provider quotas is strictly prohibited. Multiple API keys from a SINGLE authenticated account for load balancing is permitted.
- **GitHub Models Constraint**: Strictly designated as a single-key interactive fallback. Automated botting/rotation pools are forbidden to prevent developer account suspension.

---

## 6. Drex Script Modernization
- **Research Claim**: `scripts/drex_decide.py` contained hardcoded path references.
- **Correction**: Provide a modernized implementation (`scripts/drex_client.py` and updated `scripts/drex_decide.py`) that:
  - Dynamically resolves `.env` from repo root without hardcoded paths.
  - Accepts JSON inputs from `stdin` or CLI flags.
  - Automatically logs every decision (state, options, choice, probabilities, confidence, request ID) to `docs/decisions.md`.

---

## 7. License Quarantines & IP Boundaries
- **Research Claim**: Discussed porting ideas from `fcc`, `pyactr`, and `one-api`/`new-api`.
- **Correction**: Strict quarantine rules enforced:
  - **`free-claude-code` (`fcc`)** is **AGPL-3.0**: ZERO code copied. Only standard `ANTHROPIC_BASE_URL` environment redirection used.
  - **`pyactr`** is **GPL-3.0**: ZERO code copied. Clean-room mathematical reimplementation of public formulas only.
  - **`QuantumNous/new-api`** is **AGPL-3.0**: Completely excluded.
  - **`songquanpeng/one-api`**: Custom attribution clause. Excluded.
  - **`BerriAI/litellm`**: Standalone MIT router files only; do NOT touch the `enterprise/` directory.
  - All ported algorithms must provide explicit attribution in `NOTICE`.
