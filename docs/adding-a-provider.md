# Adding a provider — one config, one command (rewrite)

No code needed for OpenAI-dialect HTTP APIs. Everything else is a validated
adapter spec + measured capabilities.

## 1. Register (probes + validates with real calls)

```powershell
cd gateway
.\provider.exe add --url https://api.example.com/v1 --name myprov --key-env MYPROV_API_KEY --config config.json
.\provider.exe validate --config config.json
```

`add` fingerprints the dialect (models path, chat path, auth style, stream
format), lists models when the endpoint exists, and appends a provider entry
with `privacy_policy: public_data_only` (safe default — flip to
`zero_retention` only if the provider commits to it). Keys come from env
(never CLI args, never printed).

Manual JSON alternative — append to `providers[]` in `gateway/config.json`:

```json
{
  "name": "myprov",
  "base_url": "https://api.example.com/v1",
  "privacy_policy": "public_data_only",
  "models": ["model-a"],
  "key_pools": [{"account_label": "primary", "env_var": "MYPROV_API_KEY", "priority": 10}],
  "mirrors": [{"base_url": "https://mirror.example.com/v1", "priority": 1}],
  "adapter": {
    "dialect": "openai-chat", "chat_path": "/chat/completions",
    "models_path": "/models", "stream_format": "sse-openai",
    "auth_style": "bearer", "tool_support": "native",
    "max_tool_name": 64, "strip_keywords": ["format"], "vision": false
  }
}
```

Auth styles: `bearer` | `x-api-key` | `query-param`+`auth_param` |
`custom-header`+`auth_param` | `none` (local servers). Unknown dialect?
Set `"dialect": "unknown"` + file an issue with a sample request/response;
`validate` tells you exactly what is missing.

## 2. Probe capabilities (measured beats declared)

```powershell
.\provider.exe scan --config config.json                 # fingerprint + model diff
.\provider.exe probe --provider myprov --config config.json   # 7 cheap calls/model
```

Results land in `gateway/capabilities.json` with per-field
`source: measured|declared|assumed`. Probe budget: ~7 calls/model at
`max_tokens≤16` (≈200 tokens ≈ $0.00001 on Drex-scale pricing).

## 3. Runtime keys (no restart, DPAPI-encrypted)

```powershell
# loopback only; responses carry hashes, never keys
curl -X POST localhost:8080/v1/admin/keys -d '{"action":"add","provider":"myprov","env_var":"EXTRA","key":"..."}'
curl -X POST localhost:8080/v1/admin/keys -d '{"action":"remove","provider":"myprov","env_var":"EXTRA"}'
curl -X POST localhost:8080/v1/admin/keys -d '{"action":"set-models","provider":"myprov","key":"...","models":["model-a"]}'
curl localhost:8080/v1/admin/stats
```

Runtime keys persist DPAPI-encrypted
(`%APPDATA%\claude-master\keys.json`) on Windows; elsewhere they live in
process memory only (use env there). `pin`/`ban` models the same way.

## 4. Roles, aliases, strategies

```json
"model_aliases": {"opus": "model-a", "sonnet": "model-a", "haiku": "model-b"},
"roles": {"main": "model-a", "fast": "model-b", "subagent": "model-a"},
"routing": {"selection": "thompson_sampling|priority|round_robin|latency|cost",
            "sticky_session": false, "attempt_timeout_s": 25}
```

Any requested name (Claude IDs, aliases, unknown strings) always resolves —
never 422. Per-key model allowlists (`key_pools[].models`) + detection maps
keep requests off keys that lack access.

## 5. Verify

```powershell
python scripts\conformance.py <model>     # same scenarios, scorecard row
python scripts\e2e_gateway_live.py        # full-stack incl. streaming + tools
```

Then read `docs/compatibility-matrix.md` for what each model actually does.
