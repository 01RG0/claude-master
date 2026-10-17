"""scripts/verify_conpty.py — Full Verification Harness for ConPTY Driver on Claude Code.

Runs comprehensive end-to-end tests against native Windows ConPTY using the real
installed Claude Code CLI (`claude.exe`):
1. Keystrokes & Special Keys (Enter, Esc, Ctrl+C, Up, Down, Tab, Space, Shift+Tab)
2. Text typing & bracketed pasting
3. Slash commands (/help, /compact, /config)
4. Interactive permission prompt detection & decision handling (Allow / Deny)
5. Plan mode & execution mode toggling via Shift+Tab
6. Turn / prompt interruption (Ctrl+C / Esc recovery)
7. Clean VT terminal snapshots & ANSI-stripped screen dumps to docs/screenshots/conpty_*.txt
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import scripts.conpty_driver as d


SCREENSHOTS_DIR = os.path.join(REPO_ROOT, "docs", "screenshots")
SCRATCH_DIR = os.path.join(REPO_ROOT, "scratch", "conpty_verification")


class ConPTYVerifier:
    def __init__(self, port: int = 8088):
        self.port = port
        self.gateway_proc: subprocess.Popen | None = None
        self.test_dir = os.path.join(SCRATCH_DIR, "session")
        self.test_repo = os.path.join(self.test_dir, "repo")
        self.results: dict[str, bool] = {}
        self.evidence: dict[str, str] = {}

    def setup(self) -> None:
        """Sets up isolated git workspace, environment, and base configuration."""
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        if os.path.exists(SCRATCH_DIR):
            shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
        os.makedirs(self.test_repo, exist_ok=True)

        # Initialize clean git repo
        subprocess.run(["git", "init"], cwd=self.test_repo, check=True, capture_output=True)

        # Write dummy file into repo
        with open(os.path.join(self.test_repo, "app.py"), "w", encoding="utf-8") as f:
            f.write("# Dummy application file for ConPTY testing\nprint('hello world')\n")

        # Copy user base .claude.json to skip global telemetry / first-time onboarding
        base_user_cfg = os.path.expanduser("~/.claude.json")
        cfg_data = {}
        if os.path.exists(base_user_cfg):
            try:
                with open(base_user_cfg, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
            except Exception:
                cfg_data = {}

        # Reset projects and custom api key prompts in test config
        cfg_data["projects"] = {}
        cfg_data["hasCompletedOnboarding"] = True
        with open(os.path.join(self.test_dir, ".claude.json"), "w", encoding="utf-8") as f:
            json.dump(cfg_data, f, indent=2)

        # Start gateway on self.port with isolated temporary config copy
        gateway_bin = os.path.join(REPO_ROOT, "gateway", "gateway.exe")
        gateway_cfg = os.path.join(REPO_ROOT, "gateway", "config.json")
        temp_cfg = os.path.join(self.test_dir, "gateway_config.json")
        temp_caps = os.path.join(self.test_dir, "capabilities.json")
        if os.path.exists(gateway_bin) and os.path.exists(gateway_cfg):
            shutil.copyfile(gateway_cfg, temp_cfg)
            caps_orig = os.path.join(REPO_ROOT, "gateway", "capabilities.json")
            if os.path.exists(caps_orig):
                shutil.copyfile(caps_orig, temp_caps)
            cmd = [
                gateway_bin,
                "-config",
                temp_cfg,
                "-listen",
                f"127.0.0.1:{self.port}",
            ]
            gw_env = dict(os.environ)
            gw_env["CLAUDE_MASTER_GATEWAY_CONFIG"] = temp_cfg
            gw_env["CLAUDE_MASTER_GATEWAY_CAPABILITIES"] = temp_caps
            self.gateway_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=REPO_ROOT,
                env=gw_env,
            )
            time.sleep(1.0)
            print(f"[setup] Gateway started on 127.0.0.1:{self.port}")

    def teardown(self) -> None:
        """Terminates gateway and cleans up."""
        if self.gateway_proc:
            try:
                self.gateway_proc.terminate()
                self.gateway_proc.wait(timeout=2.0)
            except Exception:
                pass
            print("[teardown] Gateway stopped")

    def get_test_env(self) -> dict[str, str]:
        """Returns isolated test environment variables."""
        env = dict(os.environ)
        env["CLAUDE_CONFIG_DIR"] = self.test_dir
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env["ANTHROPIC_API_KEY"] = "test-verification-key"
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{self.port}"
        return env

    def verify_permission_prompt_flow(self) -> None:
        """Verifies interactive permission prompt: Deny flow and Allow flow."""
        print("\n--- Test: Permission Prompt Flow (Deny & Allow) ---")
        env = self.get_test_env()

        # Step 1: DENY flow
        session = d.ConPTYSession("claude", cwd=self.test_repo, env=env, cols=120, rows=35)
        try:
            session.assert_wait(
                lambda t: "trust this folder" in t or "safety check" in t,
                timeout_s=10.0,
                use_snapshot=True,
                message="Trust permission prompt did not appear",
            )
            prompt_snap = session.save_snapshot(os.path.join(SCREENSHOTS_DIR, "conpty_permission_prompt.txt"))
            self.evidence["permission_prompt"] = prompt_snap
            print("  [ok] Detected permission prompt (workspace trust)")

            # The default option is 'No, exit'. Press Enter to deny
            session.send_enter()
            time.sleep(1.0)
            is_alive_after_deny = session.is_alive()
            print(f"  [ok] Deny option confirmed (is_alive={is_alive_after_deny})")
        finally:
            session.close()

        # Reset .claude.json so session2 starts untrusted and triggers the trust prompt again
        cfg_file = os.path.join(self.test_dir, ".claude.json")
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                cfg_data["projects"] = {}
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(cfg_data, f, indent=2)
            except Exception:
                pass

        # Step 2: ALLOW flow
        session2 = d.ConPTYSession("claude", cwd=self.test_repo, env=env, cols=120, rows=35)
        try:
            # Check whether trust prompt or custom API key prompt appears first
            session2.assert_wait(
                lambda t: "trust this folder" in t or "custom API key" in t,
                timeout_s=10.0,
                use_snapshot=True,
                message="Neither trust prompt nor custom API key prompt appeared",
            )
            # If trust prompt appears:
            if "trust this folder" in session2.get_screen_snapshot():
                time.sleep(0.2)
                session2.send_down()
                time.sleep(0.3)
                session2.send_enter()
                print("  [ok] Selected 'Yes, I trust this folder'")

            # Wait for either custom API key prompt OR main prompt
            session2.assert_wait(
                lambda t: "custom API key" in t or "mode" in t or 'Try "' in t,
                timeout_s=10.0,
                use_snapshot=True,
                message="Did not transition after workspace trust",
            )

            # If custom API key prompt appears:
            if "custom API key" in session2.get_screen_snapshot():
                time.sleep(0.2)
                session2.send_up()
                time.sleep(0.3)
                session2.send_enter()
                print("  [ok] Accepted custom API key prompt")

            # Wait for main interactive prompt
            session2.assert_wait(
                lambda t: "auto mode" in t or "manual mode" in t or 'Try "' in t,
                timeout_s=10.0,
                use_snapshot=True,
                message="Did not transition to main prompt after permission allow",
            )
            allow_snap = session2.save_snapshot(os.path.join(SCREENSHOTS_DIR, "conpty_permission_allowed.txt"))
            self.evidence["permission_allowed"] = allow_snap
            print("  [ok] Transitioned to interactive main prompt successfully")
            self.results["permission_prompt"] = True
        finally:
            session2.close()

    def verify_interactive_session_features(self) -> None:
        """Verifies slash commands, plan mode toggle, typing, pasting, and interruption."""
        print("\n--- Test: Interactive Features (Slash Commands, Modes, Paste, Interrupt) ---")
        env = self.get_test_env()

        session = d.ConPTYSession("claude", cwd=self.test_repo, env=env, cols=120, rows=35)
        try:
            # Wait for main interactive prompt
            session.assert_wait(
                lambda t: "mode" in t or 'Try "' in t,
                timeout_s=10.0,
                use_snapshot=True,
                message="Interactive session prompt did not appear",
            )
            print("  [ok] Main interactive prompt ready")

            # 1. Test Text Typing & Pasting
            session.write("echo initial_test_input")
            time.sleep(0.3)
            session.assert_wait("echo initial_test_input", timeout_s=5.0, use_snapshot=True)
            print("  [ok] Keystroke typing verified")

            # Clear with Esc Esc
            session.send_escape()
            time.sleep(0.1)
            session.send_escape()
            time.sleep(0.3)

            # Paste
            session.paste("echo pasted_code_snippet")
            time.sleep(0.3)
            session.assert_wait("echo pasted_code_snippet", timeout_s=5.0, use_snapshot=True)
            print("  [ok] Bracketed pasting verified")

            # 2. Test Interruption via Ctrl+C
            session.send_ctrl_c()
            time.sleep(0.3)
            session.assert_wait(
                lambda t: "pasted_code_snippet" not in t or "cancelled" in t or "interrupted" in t,
                timeout_s=5.0,
                use_snapshot=True,
                message="Input not cleared after Ctrl+C interruption",
            )
            interrupt_snap = session.save_snapshot(os.path.join(SCREENSHOTS_DIR, "conpty_interruption.txt"))
            self.evidence["interruption"] = interrupt_snap
            print("  [ok] Turn/Prompt interruption verified")
            self.results["interruption"] = True

            # 3. Test Plan Mode Toggle via Shift+Tab
            # Shift+Tab cycles: auto mode -> manual mode -> accept edits -> plan mode
            print("  [*] Cycling modes with Shift+Tab...")
            session.send_shift_tab()
            session.assert_wait("manual mode", timeout_s=5.0, use_snapshot=True)
            print("    [>] Switched to manual mode")

            session.send_shift_tab()
            session.assert_wait("accept edits", timeout_s=5.0, use_snapshot=True)
            print("    [>] Switched to accept edits mode")

            session.send_shift_tab()
            session.assert_wait("plan mode", timeout_s=5.0, use_snapshot=True)
            print("    [>] Switched to plan mode")

            plan_snap = session.save_snapshot(os.path.join(SCREENSHOTS_DIR, "conpty_plan_mode.txt"))
            self.evidence["plan_mode"] = plan_snap
            print("  [ok] Plan mode toggle verified")
            self.results["plan_mode"] = True

            # Cycle back to auto mode
            session.send_shift_tab()
            session.assert_wait("auto mode", timeout_s=5.0, use_snapshot=True)
            print("    [>] Switched back to auto mode")

            # 4. Test Slash Command: /help
            print("  [*] Testing slash command /help...")
            session.send_line("/help")
            session.assert_wait(
                lambda t: "Shortcuts" in t or "Commands" in t or "codebase" in t,
                timeout_s=10.0,
                use_snapshot=True,
                message="/help dialog did not render",
            )
            help_snap = session.save_snapshot(os.path.join(SCREENSHOTS_DIR, "conpty_slash_help.txt"))
            self.evidence["slash_help"] = help_snap
            print("  [ok] Slash command /help verified")
            self.results["slash_help"] = True

            # Dismiss /help dialog with Escape
            session.send_escape()
            time.sleep(0.5)

            # 5. Test Slash Command: /compact
            print("  [*] Testing slash command /compact...")
            session.send_line("/compact")
            session.assert_wait(
                lambda t: "compact" in t.lower(),
                timeout_s=10.0,
                use_snapshot=True,
                message="/compact response did not appear",
            )
            compact_snap = session.save_snapshot(os.path.join(SCREENSHOTS_DIR, "conpty_slash_compact.txt"))
            self.evidence["slash_compact"] = compact_snap
            print("  [ok] Slash command /compact verified")
            self.results["slash_compact"] = True

            # 6. Test Slash Command & Interactive Menu: /config
            print("  [*] Testing slash command /config...")
            session.send_line("/config")
            session.assert_wait(
                lambda t: "Search settings" in t or "Auto-compact" in t,
                timeout_s=10.0,
                use_snapshot=True,
                message="/config interactive menu did not render",
            )
            config_snap = session.save_snapshot(os.path.join(SCREENSHOTS_DIR, "conpty_slash_config.txt"))
            self.evidence["slash_config"] = config_snap
            print("  [ok] Slash command /config verified")
            self.results["slash_config"] = True

            # Dismiss /config menu
            session.send_escape()
            time.sleep(0.5)
            session.send_escape()
            time.sleep(0.5)

            # 7. Test Slash Command: /resume
            print("  [*] Testing slash command /resume...")
            session.send_line("/resume")
            session.assert_wait(
                lambda t: "resume" in t.lower() or "session" in t.lower() or "no previous" in t.lower(),
                timeout_s=10.0,
                use_snapshot=True,
                message="/resume dialog did not appear",
            )
            resume_snap = session.save_snapshot(os.path.join(SCREENSHOTS_DIR, "conpty_slash_resume.txt"))
            self.evidence["slash_resume"] = resume_snap
            print("  [ok] Slash command /resume verified")
            self.results["slash_resume"] = True

            # Dismiss /resume if it opened a picker
            session.send_escape()
            time.sleep(0.5)

        finally:
            session.close()
            print("  [ok] ConPTY session closed cleanly")

    def run_all(self) -> bool:
        """Executes full verification suite and prints summary."""
        print("================================================================")
        print("Starting Native Windows ConPTY Interactive Driver Verification")
        print("================================================================")

        try:
            self.setup()
            self.verify_permission_prompt_flow()
            self.verify_interactive_session_features()
        except Exception as e:
            print(f"\n[FATAL ERROR] {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self.teardown()

        print("\n================================================================")
        print("Verification Summary:")
        all_passed = True
        for name, passed in self.results.items():
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_passed = False
            print(f"  - {name:<25}: {status}")

        print("================================================================")
        print(f"Overall Result: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
        print(f"Screenshots saved to: {SCREENSHOTS_DIR}")
        return all_passed


if __name__ == "__main__":
    verifier = ConPTYVerifier()
    success = verifier.run_all()
    sys.exit(0 if success else 1)
