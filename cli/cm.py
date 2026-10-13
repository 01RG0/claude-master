#!/usr/bin/env python3
"""
cli/cm.py — claude-master unified command-line interface.

Every cm command connects to the backend API at http://127.0.0.1:7700 using
the local auth token (.cm_token or APPDATA). Every command supports:
  --json    Machine-readable JSON output
  --curl    Print the equivalent curl command
  --api     Print the HTTP method and API endpoint
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# ANSI Colors
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
DIM = "\033[2m"

# Enable ANSI escape sequences on Windows consoles
if os.name == "nt":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def get_auth_token() -> str:
    """Retrieve auth token from env or disk."""
    env_token = os.environ.get("CM_TOKEN") or os.environ.get("CLAUDE_MASTER_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    # Search common candidate locations
    candidates = [
        os.path.join(os.getcwd(), ".cm_token"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cm_token"),
    ]
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(os.path.join(appdata, "claude-master", ".cm_token"))
    candidates.append(os.path.join(os.path.expanduser("~"), ".claude-master", ".cm_token"))

    for p in candidates:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    t = f.read().strip()
                    if t:
                        return t
            except OSError:
                continue

    try:
        from brain.api.security import get_or_create_auth_token
        return get_or_create_auth_token()
    except Exception:
        return "cm-local-dev-token"


class CMClient:
    """HTTP Client that talks to the claude-master backend API."""

    def __init__(self, base_url: str = "http://127.0.0.1:7700") -> None:
        self.base_url = os.environ.get("BRAIN_API_URL", base_url).rstrip("/")
        self.token = get_auth_token()

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        curl: bool = False,
        api_only: bool = False,
    ) -> tuple[int, Any]:
        """Send an authenticated request to the backend or display call trace."""
        query_str = ""
        if params:
            query_str = "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items() if v is not None})
        url = f"{self.base_url}{path}{query_str}"

        # 1. --api flag prints method and URL
        if api_only:
            print(f"{method.upper()} {url}")
            return 200, {"api": f"{method.upper()} {url}"}

        # 2. --curl flag prints equivalent curl command
        if curl:
            curl_cmd = f'curl -s -X {method.upper()} "{url}" -H "Authorization: Bearer {self.token}" -H "X-CM-Token: {self.token}" -H "Content-Type: application/json"'
            if body:
                curl_cmd += f" -d '{json.dumps(body)}'"
            print(curl_cmd)
            return 200, {"curl": curl_cmd}

        # 3. Standard HTTP request
        req = urllib.request.Request(url, method=method.upper())
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("X-CM-Token", self.token)
        req.add_header("Content-Type", "application/json")

        data_bytes = None
        if body is not None:
            data_bytes = json.dumps(body).encode("utf-8")

        try:
            with urllib.request.urlopen(req, data=data_bytes, timeout=10.0) as resp:
                status_code = resp.status
                raw = resp.read()
                try:
                    return status_code, json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    return status_code, raw.decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                err_data = json.loads(exc.read().decode("utf-8"))
            except Exception:
                err_data = {"error": f"HTTP {exc.code}", "message": exc.reason}
            return exc.code, err_data
        except urllib.error.URLError as exc:
            return 503, {
                "error": "daemon_unreachable",
                "message": f"Cannot connect to claude-master brain daemon at {self.base_url}: {exc.reason}. (Try running 'cm start')",
            }


# -----------------------------------------------------------------------------
# COMMAND IMPLEMENTATIONS
# -----------------------------------------------------------------------------

def cmd_status(client: CMClient, args: argparse.Namespace) -> int:
    code, data = client.request("GET", "/api/v1/status", curl=args.curl, api_only=args.api)
    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"\n{BOLD}claude-master System Status{RESET}")
    print("-" * 50)
    for comp in ["brain", "gateway", "hooks", "bypass", "drex"]:
        info = data.get(comp, {})
        st = info.get("status", "UP") if isinstance(info, dict) else ("ENABLED" if info else "OFF")
        if comp == "bypass":
            is_on = info.get("enabled", False) if isinstance(info, dict) else bool(info)
            st_badge = f"{YELLOW}ENABLED{RESET}" if is_on else f"{GREEN}OFF{RESET}"
            print(f"  [{st_badge}] Bypass Gating: {'Safety bypassed' if is_on else 'Enforced'}")
        else:
            color = GREEN if st == "UP" else RED
            extra = []
            if isinstance(info, dict):
                if "port" in info:
                    extra.append(f":{info['port']}")
                if "nodes" in info:
                    extra.append(f"{info['nodes']} nodes")
                if "active_providers_count" in info or "providers_count" in info:
                    extra.append(f"{info.get('active_providers_count', info.get('providers_count'))} providers")
            detail = " | ".join(extra)
            print(f"  [{color}{st:7}{RESET}] {comp.capitalize():<12} {detail}")
    print("-" * 50)
    return 0


def cmd_bypass(client: CMClient, args: argparse.Namespace) -> int:
    mode = (args.mode or "status").lower()
    if mode in ("on", "enable", "true"):
        code, data = client.request("POST", "/api/v1/bypass", body={"enabled": True}, curl=args.curl, api_only=args.api)
    elif mode in ("off", "disable", "false"):
        code, data = client.request("POST", "/api/v1/bypass", body={"enabled": False}, curl=args.curl, api_only=args.api)
    else:
        code, data = client.request("GET", "/api/v1/bypass", curl=args.curl, api_only=args.api)

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    enabled = data.get("enabled", False)
    if enabled:
        print(f"{YELLOW}[BYPASS ACTIVE]{RESET} Gating and stuck detectors bypassed.")
    else:
        print(f"{GREEN}[BYPASS OFF]{RESET} Full guardrails, stuck detectors, and Drex active.")
    return 0


def cmd_lifecycle(action: str, client: CMClient, args: argparse.Namespace) -> int:
    code, data = client.request("POST", f"/api/v1/control/{action}", body={"action": action, "component": "all"}, curl=args.curl, api_only=args.api)
    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"{GREEN}[ok]{RESET} {data.get('message', f'System {action} completed')}")
    return 0


def cmd_doctor(client: CMClient, args: argparse.Namespace) -> int:
    if args.fix:
        code, data = client.request("POST", "/api/v1/doctor/fix", body={"check_id": "all"}, curl=args.curl, api_only=args.api)
    else:
        code, data = client.request("GET", "/api/v1/doctor", curl=args.curl, api_only=args.api)

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"\n{BOLD}claude-master Diagnostic Report{RESET}")
    print("-" * 50)
    for check in data.get("checks", []):
        st = check.get("status")
        badge = f"{GREEN}[ok]{RESET}" if st == "pass" else (f"{YELLOW}[!!]{RESET}" if st == "warn" else f"{RED}[XX]{RESET}")
        print(f"  {badge} {check.get('name', check.get('check_id')):<24} {check.get('details', '')}")
    if data.get("applied") or data.get("fixes_applied"):
        print(f"\n{CYAN}Applied Fixes:{RESET} {data.get('message', 'Completed')}")
    print("-" * 50)
    return 0


def cmd_explain(client: CMClient, args: argparse.Namespace) -> int:
    code, data = client.request("GET", f"/api/v1/explain/{args.req_id}", curl=args.curl, api_only=args.api)
    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"\n{BOLD}Request Decision Breakdown ({data.get('request_id', args.req_id)}){RESET}")
    print("-" * 50)
    print(f"  Model Requested:   {data.get('requested_model', 'claude-3-7-sonnet')}")
    print(f"  Provider Selected: {CYAN}{data.get('actual_provider', 'anthropic')}{RESET}")
    print(f"  Routing Reason:    {data.get('routing_reason', 'Optimal latency')}")
    drex = data.get("drex", {})
    print(f"  Drex Gating:       {drex.get('gating_action', 'allow')} (score: {drex.get('risk_score', 0.05)})")
    perf = data.get("performance", {})
    print(f"  Latency:           {perf.get('total_latency_ms', 140)}ms")
    print("-" * 50)
    return 0


def cmd_provider(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "list").lower()
    if sub == "list":
        code, data = client.request("GET", "/api/v1/providers", curl=args.curl, api_only=args.api)
    elif sub == "add":
        payload = {
            "name": args.name or "custom",
            "base_url": args.url or "https://api.openai.com/v1",
            "models": args.models.split(",") if args.models else ["gpt-4o"],
        }
        code, data = client.request("POST", "/api/v1/providers", body=payload, curl=args.curl, api_only=args.api)
    elif sub == "remove":
        code, data = client.request("DELETE", f"/api/v1/providers/{args.name}", curl=args.curl, api_only=args.api)
    elif sub == "test" or sub == "probe" or sub == "scan":
        code, data = client.request("POST", "/api/v1/providers/test", body={"provider": args.name or "anthropic"}, curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown provider subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    if sub == "list":
        provs = data if isinstance(data, list) else data.get("providers", [])
        print(f"\n{BOLD}Configured Providers ({len(provs)}){RESET}")
        print("-" * 60)
        for p in provs:
            name = p.get("name") or p.get("Name")
            base = p.get("base_url", "")
            mods = p.get("models") or p.get("Models") or []
            print(f"  - {CYAN}{name:<16}{RESET} {base:<32} models: {len(mods)}")
        print("-" * 60)
    else:
        print(f"{GREEN}[ok]{RESET} Provider operation '{sub}' succeeded:\n{json.dumps(data, indent=2)}")
    return 0


def cmd_key(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "list").lower()
    if sub == "list":
        code, data = client.request("GET", "/api/v1/keys", curl=args.curl, api_only=args.api)
    elif sub == "add":
        code, data = client.request("POST", "/api/v1/keys", body={"provider": args.provider or "anthropic", "key": args.key or "sk-test", "env_var": args.env or "ANTHROPIC_API_KEY"}, curl=args.curl, api_only=args.api)
    elif sub == "remove":
        prov = args.provider or "anthropic"
        code, data = client.request("DELETE", "/api/v1/keys", params={"provider": prov, "env_var": args.key_id or args.env or ""}, curl=args.curl, api_only=args.api)
    elif sub == "rotate":
        code, data = client.request("PUT", "/api/v1/keys/rotate", body={"provider": args.provider or "anthropic", "env_var": args.env or "ANTHROPIC_API_KEY", "new_key": args.key or "sk-new"}, curl=args.curl, api_only=args.api)
    elif sub == "test":
        code, data = client.request("POST", "/api/v1/providers/test", body={"provider": args.provider or "anthropic"}, curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown key subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    if sub == "list":
        keys = data if isinstance(data, list) else data.get("keys", [])
        print(f"\n{BOLD}Active Keys ({len(keys)}) — Secrets Masked{RESET}")
        print("-" * 60)
        for k in keys:
            prov = k.get("provider", "")
            env_var = k.get("env_var", "")
            mask = k.get("masked_key") or k.get("mask", "***")
            st = k.get("health", "active")
            print(f"  {prov:<14} {CYAN}{env_var:<24}{RESET} mask: {mask:<12} [{GREEN}{st}{RESET}]")
        print("-" * 60)
    else:
        print(f"{GREEN}[ok]{RESET} Key operation '{sub}' succeeded:\n{json.dumps(data, indent=2)}")
    return 0


def cmd_model(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "list").lower()
    if sub == "list":
        code, data = client.request("GET", "/api/v1/models", curl=args.curl, api_only=args.api)
    elif sub == "probe":
        code, data = client.request("POST", "/api/v1/models/probe", params={"model_id": args.model or "claude-3-7-sonnet"}, curl=args.curl, api_only=args.api)
    elif sub == "pin":
        m_list = [args.model] if args.model else ["claude-3-7-sonnet"]
        code, data = client.request("POST", "/api/v1/models/pin", body={"models": m_list}, curl=args.curl, api_only=args.api)
    elif sub == "ban":
        m_list = [args.model] if args.model else ["bad-model"]
        code, data = client.request("POST", "/api/v1/models/ban", body={"models": m_list}, curl=args.curl, api_only=args.api)
    elif sub == "override":
        code, data = client.request("PUT", "/api/v1/models/override", body={"model_id": args.alias or "fast", "capabilities": {"streaming": True, "tools": True}}, curl=args.curl, api_only=args.api)
    elif sub == "compare":
        code, data = client.request("POST", "/api/v1/models/compare", body={"model_ids": ["claude-3-7-sonnet", "gpt-4o"]}, curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown model subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    if sub == "list" or sub == "compare":
        models = data if isinstance(data, list) else data.get("models", [])
        print(f"\n{BOLD}Models Catalog ({len(models)}){RESET}")
        print("-" * 65)
        for m in models:
            m_id = m.get("model_id") or m.get("id")
            prov = m.get("provider", "")
            ctx = m.get("context_window", "")
            pin_badge = f"{CYAN}[PINNED]{RESET}" if m.get("pinned") else ""
            ban_badge = f"{RED}[BANNED]{RESET}" if m.get("banned") else ""
            print(f"  {m_id:<28} {prov:<12} ctx: {ctx:<8} {pin_badge} {ban_badge}")
        print("-" * 65)
    else:
        print(f"{GREEN}[ok]{RESET} Model operation '{sub}' succeeded:\n{json.dumps(data, indent=2)}")
    return 0


def cmd_route(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "get").lower()
    if sub == "get":
        code, data = client.request("GET", "/api/v1/routing", curl=args.curl, api_only=args.api)
    elif sub == "set":
        code, data = client.request("PUT", "/api/v1/routing", body={"strategy": args.strategy or "dynamic_expected_utility"}, curl=args.curl, api_only=args.api)
    elif sub == "simulate":
        task = getattr(args, "task", None) or getattr(args, "model", None) or (args.strategy if args.strategy and args.strategy not in ("simulate", "get", "set", "explain", "profiles") else "General agentic coding")
        profile = getattr(args, "profile", None) or "main"
        tokens = getattr(args, "tokens", 500) or 500
        req_vision = bool(getattr(args, "vision", False))
        body = {
            "task": task,
            "role": profile,
            "prompt_tokens": tokens,
            "requires_vision": req_vision,
        }
        code, data = client.request("POST", "/api/v1/routing/simulate", body=body, curl=args.curl, api_only=args.api)
        if args.curl or args.api:
            return 0
        if args.json or code != 200:
            print(json.dumps(data, indent=2))
            return 0 if code == 200 else 1

        print(f"\n{BOLD}Dynamic Route Simulation{RESET}")
        print("-" * 55)
        print(f"  {BOLD}Profile:{RESET}          {data.get('resolved_role', profile)}")
        print(f"  {BOLD}Selected Model:{RESET}   {data.get('selected_model', 'unknown')}")
        print(f"  {BOLD}Provider:{RESET}         {data.get('selected_provider', 'unknown')}")
        print(f"  {BOLD}Decision Source:{RESET}  {data.get('decision_source', 'deterministic')}")
        if data.get("confidence") is not None:
            print(f"  {BOLD}Confidence:{RESET}       {data.get('confidence'):.2f}")
        print(f"  {BOLD}Est. Cost:{RESET}        ${data.get('estimated_cost_usd', 0.0):.6f}")
        print(f"  {BOLD}Reason:{RESET}           {data.get('selection_reason', '')}")
        fb = data.get("fallback_chain", [])
        if fb:
            print(f"  {BOLD}Fallback Chain:{RESET}   {' -> '.join(fb)}")
        if data.get("request_id"):
            print(f"  {BOLD}Request ID:{RESET}       {data.get('request_id')}")
        return 0

    elif sub == "profiles":
        code, data = client.request("GET", "/api/v1/routing/profiles", curl=args.curl, api_only=args.api)
        if args.curl or args.api:
            return 0
        if args.json or code != 200:
            print(json.dumps(data, indent=2))
            return 0 if code == 200 else 1

        print(f"\n{BOLD}Requirement Profiles{RESET}")
        print("-" * 80)
        print(f"{'Profile':<18} {'Tools':<7} {'Vision':<7} {'Context':<9} {'Budget':<8} {'Weights (Q/T/C/R)'}")
        print("-" * 80)
        for p in data:
            hard = p.get("hard_constraints", {})
            soft = p.get("soft_objectives", {})
            tools_str = "yes" if hard.get("tool_calling") else "no"
            vis_str = "yes" if hard.get("vision") else "no"
            ctx_str = f"{hard.get('min_context', 0):,}"
            bud_str = f"${hard.get('max_budget_usd', 0.0):.2f}"
            obj_str = f"{soft.get('quality', 0):.2f}/{soft.get('ttft', 0):.2f}/{soft.get('cost', 0):.2f}/{soft.get('reliability', 0):.2f}"
            print(f"{p.get('name', ''):<18} {tools_str:<7} {vis_str:<7} {ctx_str:<9} {bud_str:<8} {obj_str}")
        print("-" * 80)
        return 0

    elif sub == "explain":
        req_id = getattr(args, "req_id", None) or args.strategy
        if not req_id:
            print("Error: Request ID is required for explain. Usage: cm route explain <req-id>")
            return 1
        code, data = client.request("GET", f"/api/v1/routing/explain/{req_id}", curl=args.curl, api_only=args.api)
        if args.curl or args.api:
            return 0
        if args.json or code != 200:
            print(json.dumps(data, indent=2))
            return 0 if code == 200 else 1

        print(f"\n{BOLD}Routing Decision Explanation [{req_id}]{RESET}")
        print("-" * 65)
        if "decision" in data:
            dec = data.get("decision", {})
            task = data.get("task_understanding", {})
            print(f"  {BOLD}Selected Route:{RESET}    {dec.get('selected_route_id', dec.get('selected_model'))}")
            print(f"  {BOLD}Model / Provider:{RESET}  {dec.get('selected_model')} ({dec.get('selected_provider')})")
            print(f"  {BOLD}Decision Source:{RESET}   {dec.get('decision_source')} (confidence: {dec.get('confidence')})")
            print(f"  {BOLD}Task Type:{RESET}          {task.get('task_type')} | Complexity: {task.get('complexity')} | Lang: {task.get('language')}")
            print(f"  {BOLD}Reason:{RESET}             {dec.get('reason')}")
            scored = data.get("all_scored_candidates", [])
            if scored:
                print(f"\n  {BOLD}Scored Candidates:{RESET}")
                for s in scored:
                    m = s.get("metrics", {})
                    print(f"    - {m.get('route_id')}: utility={s.get('utility_score'):.3f} (Q={s.get('quality_score'):.2f}, TTFT={m.get('measured_ttft_ms'):.0f}ms, Cost=${s.get('estimated_cost_usd'):.5f})")
            filtered = data.get("filtered_out", {})
            if filtered:
                print(f"\n  {BOLD}Filtered Out:{RESET}")
                for r_id, r_why in filtered.items():
                    print(f"    - {r_id}: {r_why}")
        else:
            if "plain_explanation" in data:
                print(f"  Summary: {data['plain_explanation']}")
            print(f"  Task Classification: {json.dumps(data.get('task_classification', {}))}")
            print(f"  Candidates: {', '.join(data.get('candidates', []))}")
            print(f"  Scores: {json.dumps(data.get('scores', {}), indent=4)}")
            choice = data.get("final_choice", {})
            print(f"  Final Choice: {choice.get('model_id', 'none')} (score: {choice.get('score', 0.0)}) - {choice.get('reason', '')}")
        return 0
    else:
        print(f"Unknown route subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"{GREEN}[ok]{RESET} Route operation '{sub}':\n{json.dumps(data, indent=2)}")
    return 0


def cmd_drex(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "status").lower()
    if sub in ("status", "accuracy", "decisions"):
        code, data = client.request("GET", "/api/v1/drex", curl=args.curl, api_only=args.api)
    elif sub == "config":
        body = {}
        if args.timeout:
            body["timeout_s"] = float(args.timeout)
        if args.guard_drex is not None:
            body["enable_for_guard"] = args.guard_drex.lower() == "on"
        code, data = client.request("PUT", "/api/v1/drex", body=body, curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown drex subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"\n{BOLD}Drex Evaluation System [{sub.upper()}]{RESET}")
    print("-" * 50)
    for k, v in data.items():
        print(f"  {k:<24} {v}")
    print("-" * 50)
    return 0


def cmd_privacy(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "rules").lower()
    if sub in ("rules", "guards"):
        code, data = client.request("GET", "/api/v1/privacy", curl=args.curl, api_only=args.api)
    elif sub == "redact":
        code, data = client.request("POST", "/api/v1/privacy/preview", body={"text": args.text or "Sample secret sk-1234567890abcdef"}, curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown privacy subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    if sub == "redact":
        print(f"\n{BOLD}Redacted Output:{RESET}\n{data.get('redacted')}")
    else:
        print(json.dumps(data, indent=2))
    return 0


def cmd_budget(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "summary").lower()
    if sub in ("summary", "projections"):
        code, data = client.request("GET", "/api/v1/budgets", curl=args.curl, api_only=args.api)
    elif sub == "caps":
        body = {}
        if args.daily:
            body["daily_cap_usd"] = float(args.daily)
        if args.monthly:
            body["monthly_cap_usd"] = float(args.monthly)
        code, data = client.request("PUT", "/api/v1/budgets", body=body, curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown budget subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"\n{BOLD}Budget & Usage [{sub.upper()}]{RESET}")
    print("-" * 50)
    for k, v in data.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for sub_k, sub_v in v.items():
                print(f"    - {sub_k:<16} ${sub_v}")
        else:
            print(f"  {k:<25} {v}")
    print("-" * 50)
    return 0


def cmd_brain(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "lessons").lower()
    if sub in ("lessons", "memories"):
        code, data = client.request("GET", "/api/v1/brain/memory", curl=args.curl, api_only=args.api)
    elif sub == "decay":
        code, data = client.request("POST", "/api/v1/brain/memory/decay", curl=args.curl, api_only=args.api)
    elif sub == "rollback":
        code, data = client.request("POST", "/api/v1/brain/memory/rollback", params={"snapshot_id": "snap-latest"}, curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown brain subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"{GREEN}[ok]{RESET} Brain operation '{sub}':\n{json.dumps(data, indent=2)}")
    return 0


def cmd_claude(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "status").lower()
    if sub == "status":
        code, data = client.request("GET", "/api/v1/claude", curl=args.curl, api_only=args.api)
    elif sub == "apply":
        code, data = client.request("POST", "/api/v1/claude/configure", body={"action": "route_to_gateway"}, curl=args.curl, api_only=args.api)
    elif sub == "undo":
        code, data = client.request("POST", "/api/v1/claude/undo", curl=args.curl, api_only=args.api)
    elif sub == "verify":
        code, data = client.request("POST", "/api/v1/claude/verify", curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown claude subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"\n{BOLD}Claude Code Integration [{sub.upper()}]{RESET}")
    print("-" * 50)
    for k, v in data.items():
        print(f"  {k:<24} {v}")
    print("-" * 50)
    return 0


def cmd_test(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "smoke").lower()
    if sub in ("run", "smoke"):
        suite = "smoke" if sub == "smoke" else (args.suite or "standard")
        code, data = client.request("POST", "/api/v1/test-center/run", body={"suite": suite}, curl=args.curl, api_only=args.api)
    elif sub == "status":
        code, data = client.request("GET", "/api/v1/test-center/status", curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown test subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"{GREEN}[ok]{RESET} Test operation '{sub}':\n{json.dumps(data, indent=2)}")
    return 0


def cmd_backup(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "list").lower()
    if sub == "list":
        code, data = client.request("GET", "/api/v1/backup", curl=args.curl, api_only=args.api)
    elif sub == "create":
        code, data = client.request("POST", "/api/v1/backup", params={"notes": args.name or "manual"}, curl=args.curl, api_only=args.api)
    elif sub == "restore":
        b_id = args.backup_id or args.name or "latest"
        code, data = client.request("POST", "/api/v1/backup/restore", body={"backup_id": b_id}, curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown backup subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(f"{GREEN}[ok]{RESET} Backup '{sub}' succeeded:\n{json.dumps(data, indent=2)}")
    return 0


def cmd_update(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "check").lower()
    if sub == "check":
        code, data = client.request("GET", "/api/v1/update", curl=args.curl, api_only=args.api)
    elif sub == "apply":
        code, data = client.request("POST", "/api/v1/update", body={"mock": True}, curl=args.curl, api_only=args.api)
    elif sub == "rollback":
        code, data = client.request("POST", "/api/v1/backup/restore", body={"backup_id": "latest"}, curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown update subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(json.dumps(data, indent=2))
    return 0


def cmd_config(client: CMClient, args: argparse.Namespace) -> int:
    sub = (args.subcommand or "export").lower()
    if sub == "export":
        code, data = client.request("GET", "/api/v1/schema", curl=args.curl, api_only=args.api)
    elif sub == "import" or sub == "reset":
        code, data = client.request("GET", "/api/v1/schema", curl=args.curl, api_only=args.api)
    else:
        print(f"Unknown config subcommand: {sub}")
        return 1

    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    print(json.dumps(data, indent=2))
    return 0


def cmd_logs(client: CMClient, args: argparse.Namespace) -> int:
    if args.export:
        code, data = client.request("POST", "/api/v1/logs/bundle", curl=args.curl, api_only=args.api)
        if args.curl or args.api:
            return 0
        print(f"{GREEN}[ok]{RESET} Logs exported successfully.")
        return 0

    params = {}
    if args.level:
        params["level"] = args.level
    code, data = client.request("GET", "/api/v1/logs", params=params, curl=args.curl, api_only=args.api)
    if args.curl or args.api:
        return 0
    if args.json or code != 200:
        print(json.dumps(data, indent=2))
        return 0 if code == 200 else 1

    logs_list = data if isinstance(data, list) else data.get("logs", [])
    print(f"\n{BOLD}Recent System Logs ({len(logs_list)}){RESET}")
    print("-" * 65)
    for item in logs_list:
        if isinstance(item, dict):
            ts = item.get("timestamp", "")
            lvl = item.get("level", "INFO")
            msg = item.get("message", "")
            print(f"  [{ts}] {lvl:<5} {msg}")
        else:
            print(f"  {item}")
    print("-" * 65)
    return 0


# -----------------------------------------------------------------------------
# ARGUMENT PARSER SETUP
# -----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    common_parser.add_argument("--curl", action="store_true", help="Print equivalent curl command")
    common_parser.add_argument("--api", action="store_true", help="Print underlying HTTP endpoint")

    parser = argparse.ArgumentParser(
        prog="cm",
        description="claude-master — universal CLI management tool",
        formatter_class=argparse.RawTextHelpFormatter,
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. status
    p_status = subparsers.add_parser("status", help="One-screen component health", parents=[common_parser])
    p_status.set_defaults(func=cmd_status)

    # 2. bypass
    p_bypass = subparsers.add_parser("bypass", help="Query or toggle bypass mode", parents=[common_parser])
    p_bypass.add_argument("mode", nargs="?", choices=["on", "off", "status"], default="status", help="bypass mode")
    p_bypass.set_defaults(func=cmd_bypass)

    # 3. start / stop / restart
    p_start = subparsers.add_parser("start", help="Start system stack", parents=[common_parser])
    p_start.set_defaults(func=lambda c, a: cmd_lifecycle("start", c, a))

    p_stop = subparsers.add_parser("stop", help="Stop system stack", parents=[common_parser])
    p_stop.set_defaults(func=lambda c, a: cmd_lifecycle("stop", c, a))

    p_restart = subparsers.add_parser("restart", help="Restart system stack", parents=[common_parser])
    p_restart.set_defaults(func=lambda c, a: cmd_lifecycle("restart", c, a))

    # 4. doctor
    p_doctor = subparsers.add_parser("doctor", help="Run system diagnostics and auto-fixes", parents=[common_parser])
    p_doctor.add_argument("--fix", action="store_true", help="Apply automated fixes")
    p_doctor.set_defaults(func=cmd_doctor)

    # 5. explain
    p_explain = subparsers.add_parser("explain", help="Explain routing and safety decisions", parents=[common_parser])
    p_explain.add_argument("req_id", help="Request ID to explain")
    p_explain.set_defaults(func=cmd_explain)

    # 6. provider
    p_prov = subparsers.add_parser("provider", help="Manage model providers", parents=[common_parser])
    p_prov.add_argument("subcommand", nargs="?", choices=["list", "add", "remove", "test", "scan", "probe"], default="list")
    p_prov.add_argument("name", nargs="?", help="Provider name")
    p_prov.add_argument("--url", help="Base URL for provider")
    p_prov.add_argument("--models", help="Comma-separated models list")
    p_prov.set_defaults(func=cmd_provider)

    # 7. key
    p_key = subparsers.add_parser("key", help="Manage provider API keys", parents=[common_parser])
    p_key.add_argument("subcommand", nargs="?", choices=["list", "add", "remove", "rotate", "test"], default="list")
    p_key.add_argument("provider", nargs="?", help="Provider name")
    p_key.add_argument("key", nargs="?", help="Key string")
    p_key.add_argument("--env", help="Environment variable name")
    p_key.add_argument("--key-id", help="Key identifier or env_var")
    p_key.set_defaults(func=cmd_key)

    # 8. model
    p_model = subparsers.add_parser("model", help="Inspect and control models", parents=[common_parser])
    p_model.add_argument("subcommand", nargs="?", choices=["list", "probe", "pin", "ban", "override", "compare"], default="list")
    p_model.add_argument("model", nargs="?", help="Model ID")
    p_model.add_argument("--alias", help="Alias for override")
    p_model.add_argument("--target", help="Target model for override")
    p_model.set_defaults(func=cmd_model)

    # 9. route
    p_route = subparsers.add_parser("route", help="Routing strategies and policies", parents=[common_parser])
    p_route.add_argument("subcommand", nargs="?", choices=["get", "set", "simulate", "explain", "profiles"], default="get")
    p_route.add_argument("strategy", nargs="?", help="Strategy name, profile name, or request ID for explain")
    p_route.add_argument("--model", help="Model to simulate")
    p_route.add_argument("--task", help="Task prompt or description to simulate")
    p_route.add_argument("--profile", help="Requirement profile name (main, fast, vision, etc.)")
    p_route.add_argument("--tokens", type=int, default=500, help="Prompt token count for simulation")
    p_route.add_argument("--vision", action="store_true", help="Task requires multimodal vision")
    p_route.add_argument("--req-id", dest="req_id", help="Request ID to explain")
    p_route.set_defaults(func=cmd_route)

    # 10. drex
    p_drex = subparsers.add_parser("drex", help="Drex safety judge and gating", parents=[common_parser])
    p_drex.add_argument("subcommand", nargs="?", choices=["status", "config", "decisions", "accuracy"], default="status")
    p_drex.add_argument("--timeout", help="Timeout in seconds")
    p_drex.add_argument("--guard-drex", choices=["on", "off"], help="Toggle Drex for guard gating")
    p_drex.set_defaults(func=cmd_drex)

    # 11. privacy
    p_priv = subparsers.add_parser("privacy", help="Privacy rules and PII redaction", parents=[common_parser])
    p_priv.add_argument("subcommand", nargs="?", choices=["rules", "redact", "guards"], default="rules")
    p_priv.add_argument("text", nargs="?", help="Text to test redaction on")
    p_priv.set_defaults(func=cmd_privacy)

    # 12. budget
    p_bud = subparsers.add_parser("budget", help="Token expenditure and spend caps", parents=[common_parser])
    p_bud.add_argument("subcommand", nargs="?", choices=["summary", "caps", "projections"], default="summary")
    p_bud.add_argument("--daily", help="Daily cap in USD")
    p_bud.add_argument("--monthly", help="Monthly cap in USD")
    p_bud.set_defaults(func=cmd_budget)

    # 13. brain
    p_brain = subparsers.add_parser("brain", help="Brain memory and lessons store", parents=[common_parser])
    p_brain.add_argument("subcommand", nargs="?", choices=["lessons", "memories", "decay", "rollback"], default="lessons")
    p_brain.add_argument("--steps", type=int, default=1, help="Rollback steps")
    p_brain.set_defaults(func=cmd_brain)

    # 14. claude
    p_claude = subparsers.add_parser("claude", help="Claude Code integration controls", parents=[common_parser])
    p_claude.add_argument("subcommand", nargs="?", choices=["status", "apply", "undo", "verify"], default="status")
    p_claude.set_defaults(func=cmd_claude)

    # 15. test
    p_test = subparsers.add_parser("test", help="Execute automated test suites", parents=[common_parser])
    p_test.add_argument("subcommand", nargs="?", choices=["run", "smoke", "status"], default="smoke")
    p_test.add_argument("--suite", help="Suite to run")
    p_test.set_defaults(func=cmd_test)

    # 16. backup
    p_bk = subparsers.add_parser("backup", help="Manage system backups", parents=[common_parser])
    p_bk.add_argument("subcommand", nargs="?", choices=["create", "restore", "list"], default="list")
    p_bk.add_argument("name", nargs="?", help="Backup name or ID")
    p_bk.add_argument("--backup-id", help="Backup ID to restore")
    p_bk.set_defaults(func=cmd_backup)

    # 17. update
    p_upd = subparsers.add_parser("update", help="Update claude-master binaries and components", parents=[common_parser])
    p_upd.add_argument("subcommand", nargs="?", choices=["check", "apply", "rollback"], default="check")
    p_upd.set_defaults(func=cmd_update)

    # 18. config
    p_cfg = subparsers.add_parser("config", help="Export and import system configurations", parents=[common_parser])
    p_cfg.add_argument("subcommand", nargs="?", choices=["export", "import", "reset"], default="export")
    p_cfg.add_argument("config_data", nargs="?", help="JSON string for import")
    p_cfg.set_defaults(func=cmd_config)

    # 19. logs
    p_logs = subparsers.add_parser("logs", help="View or export runtime logs", parents=[common_parser])
    p_logs.add_argument("--level", choices=["INFO", "WARN", "ERROR", "DEBUG"], help="Log level filter")
    p_logs.add_argument("--follow", action="store_true", help="Follow log stream")
    p_logs.add_argument("--export", help="Export logs to specified destination path")
    p_logs.set_defaults(func=cmd_logs)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    client = CMClient()
    func = getattr(args, "func", None)
    if func:
        return func(client, args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
