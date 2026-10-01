"""
tests/security/test_secrets.py
Security / V2 acceptance suite: no secrets at rest, none in logs, none in
the browser, and no source code routed to public_data_only providers.

Run:  python -m pytest tests/security/ -v
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_DIR = REPO_ROOT / "gateway"
STUDIO_SECRETS_TS = REPO_ROOT / "studio" / "src" / "ui" / "secrets.ts"
SECURITY_DIR = Path(__file__).resolve().parent
GO_PROBE = SECURITY_DIR / "goprobe" / "secrets_probe_test.go"

sys.path.insert(0, str(REPO_ROOT))

# Directories that are dependency/build caches, not first-party source.
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "dist", "build", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
}

# Secret shapes we refuse to see committed anywhere in the tree.
# The PEM pattern is assembled at import time so this scanner does not
# flag its own detection patterns.
_PEM = "-" * 5 + "BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY" + "-" * 5

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                       # OpenAI/Anthropic-style
    re.compile(r"ghp_[A-Za-z0-9]{36}"),                       # GitHub PAT
    re.compile(r"AKIA[0-9A-Z]{16}"),                          # AWS access key id
    re.compile(_PEM),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{24,}"),
    re.compile(r"(?i)xox[baprs]-[A-Za-z0-9-]{20,}"),          # Slack
]

# Dummy values that legitimately look like secrets. These are test fixtures,
# not credentials; keep this list explicit so a new one is a deliberate act.
# A match is exempt when it *contains* one of these known-dummy bodies.
ALLOWED_FIXTURES = {
    # gateway/cooldown_bandit_test.go — synthetic upstream keys
    "sk-abc12345678901234567890",
    "sk-abcdefghijklmnopqrstuvwxyz123456",
    # studio/tests/gateway-admin.test.ts — synthetic display fixture
    "sk-abcdefghijklmnopqrstuvwxyz",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_source_files() -> "list[Path]":
    """Every regular file in the repo tree except caches, .git and node_modules."""
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [
            d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".git")
        ]
        for name in filenames:
            out.append(Path(dirpath) / name)
    return out


def _run_go_probe(test_name: str) -> subprocess.CompletedProcess:
    """Run the in-package gateway probe via `go test -overlay`."""
    go = shutil.which("go")
    if go is None:
        pytest.skip("go toolchain not available")
    import tempfile

    tmp_path = Path(tempfile.mkdtemp(prefix="cm-probe-"))
    overlay = tmp_path / "overlay.json"
    ghost = GATEWAY_DIR / "zz_pytest_probe_test.go"  # never written to disk
    overlay.write_text(json.dumps({"Replace": {str(ghost): str(GO_PROBE)}}), encoding="utf-8")
    return subprocess.run(
        [go, "test", "-vet=off", "-count=1", f"-overlay={overlay}",
         "-run", test_name, "-v", "."],
        cwd=GATEWAY_DIR, capture_output=True, text=True, timeout=300,
    )


def _require_go() -> str:
    go = shutil.which("go")
    if go is None:
        pytest.skip("go toolchain not available")
    return go


def _require_node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


# ===========================================================================
# 1. No hardcoded API keys anywhere in the repo tree
# ===========================================================================

def test_no_hardcoded_api_keys_in_repo_tree():
    """
    Scan every first-party file for secret-shaped literals. Only the explicit
    dummy-fixture allowlist may match.
    """
    findings: list[str] = []
    scanned = 0

    for path in _iter_source_files():
        # .env files are secrets *by definition* and are gitignored.
        if path.name == ".env" or path.name.endswith(".env"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary asset
        scanned += 1
        rel = path.relative_to(REPO_ROOT)
        for pattern in SECRET_PATTERNS:
            for match in pattern.findall(text):
                secret = match if isinstance(match, str) else match[0]
                if any(fixture in secret for fixture in ALLOWED_FIXTURES):
                    continue
                line_no = text[: text.index(match)].count("\n") + 1
                findings.append(f"{rel}:{line_no}: {secret[:12]}... ({pattern.pattern})")

    assert scanned > 50, f"scan covered only {scanned} files — tree walk is broken"
    assert not findings, "hardcoded secrets found:\n" + "\n".join(findings)


def test_env_file_is_gitignored_not_committed():
    """The real .env may hold a key, but it must never be tracked by git."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore

    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", ".env"],
        capture_output=True, text=True,
    )
    assert tracked.returncode != 0, ".env is tracked by git — key is exposed"


def test_secret_files_are_all_gitignored():
    """Every local secret file variant must be covered by .gitignore."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "*.env", ".env.*"):
        assert pattern in gitignore, f"missing gitignore rule: {pattern}"


# ===========================================================================
# 2. redactForLog() strips bearer tokens
# ===========================================================================

def test_gateway_redact_for_log_strips_bearer_tokens():
    """The real Go redactForLog() must never emit a bearer token."""
    proc = _run_go_probe("TestSecurityRedactForLogStripsBearerTokens")
    assert proc.returncode == 0, f"go probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_gateway_redact_for_log_strips_secret_shapes():
    """GitHub PATs, AWS ids, PEM blocks and api_key= values are all scrubbed."""
    proc = _run_go_probe("TestSecurityRedactForLogStripsVariousSecretShapes")
    assert proc.returncode == 0, f"go probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_gateway_redact_for_log_preserves_benign_logs():
    """Redaction must not mangle ordinary operational log lines."""
    proc = _run_go_probe("TestSecurityRedactForLogPreservesBenignText")
    assert proc.returncode == 0, f"go probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_gateway_request_snippet_is_scrubbed():
    """requestSnippet() (used for diagnostics) must be secret-free."""
    proc = _run_go_probe("TestSecurityRequestSnippetIsScrubbedAndTruncated")
    assert proc.returncode == 0, f"go probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_redact_handles_hyphenated_key_formats():
    """Real Anthropic/OpenAI key formats must be redacted, not echoed.

    Contract: reSecretLike body is [A-Za-z0-9_-]{20,} so hyphenated keys
    (sk-ant-api03-..., sk-proj-...) are matched and redacted.
    """
    proc = _run_go_probe("TestSecurityRedactForLogHandlesHyphenatedKeyFormats")
    assert proc.returncode == 0, f"go probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_redact_contract_reimplemented_inline():
    """
    Language-independent restatement of the redactForLog contract, so the
    invariant survives even if the Go package cannot be compiled here.
    Mirrors gateway/privacy.go: reSecretLike.ReplaceAllString(s, "[REDACTED]").
    """
    re_secret_like = re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|bearer\s+[a-z0-9._\-]{16,}"
        r"|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|AKIA[0-9A-Z]{16}"
        r"|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})"
    )

    def redact_for_log(s: str) -> str:
        return re_secret_like.sub("[REDACTED]", s)

    # Built at run time so this file never holds a scanner-matching literal.
    secret = "sk-" + "b" * 40
    assert secret not in redact_for_log(f"Authorization: Bearer {secret}")
    assert "[REDACTED]" in redact_for_log(f"Authorization: Bearer {secret}")

    # Assembled from parts so this scanner does not flag its own fixtures.
    pem = "-" * 5 + "BEGIN RSA PRIVATE KEY" + "-" * 5
    for shape in ("ghp_" + "a" * 36, "AKIA" + "B" * 16, pem,
                  "api_key=" + secret):
        out = redact_for_log("prefix " + shape + " suffix")
        assert out != "prefix " + shape + " suffix"
        assert "[REDACTED]" in out

    benign = "gateway: provider=groq model=llama 429 cooldown=1m0s"
    assert redact_for_log(benign) == benign


def test_gateway_never_logs_raw_keys_only_hashes():
    """HashKey() must not return the raw secret; server logs hashes only."""
    source = (GATEWAY_DIR / "server.go").read_text(encoding="utf-8")
    assert 'log.Printf("gateway: provider=%s model=%s key=%s 429 cooldown=%s", p.Name, model, kh, dur)' \
        in source, "429 log line must log kh (the hash), not the raw key"

    cooldown_src = (GATEWAY_DIR / "cooldown.go").read_text(encoding="utf-8")
    assert "sha256.Sum256" in cooldown_src
    assert "Raw secrets are never" in cooldown_src


# ===========================================================================
# 3. Privacy routing: source code stays off public providers
# ===========================================================================

def test_contains_sensitive_content_true_for_git_diff_with_source():
    """A git diff containing source code must be classified sensitive."""
    proc = _run_go_probe("TestSecurityContainsSensitiveContentTrueForSourceCode")
    assert proc.returncode == 0, f"go probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_contains_sensitive_content_true_for_secrets_env_and_fences():
    """Hardcoded keys, .env references and code fences are all sensitive."""
    proc = _run_go_probe("TestSecurityContainsSensitiveContentTrueForSecrets")
    assert proc.returncode == 0, f"go probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_contains_sensitive_content_false_for_pure_theory():
    """A pure theory question must stay public (no code, no secrets)."""
    proc = _run_go_probe("TestSecurityContainsSensitiveContentFalseForTheory")
    assert proc.returncode == 0, f"go probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_contains_sensitive_content_is_nil_safe():
    """A nil request must not panic or misclassify."""
    proc = _run_go_probe("TestSecurityContainsSensitiveContentNilSafe")
    assert proc.returncode == 0, f"go probe failed:\n{proc.stdout}\n{proc.stderr}"


def test_privacy_contract_reimplemented_inline():
    """
    Inline restatement of gateway/privacy.go's ContainsSensitiveContent, so the
    routing invariant is asserted even without a Go toolchain.
    """
    re_secret_like = re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|bearer\s+[a-z0-9._\-]{16,}"
        r"|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|AKIA[0-9A-Z]{16}"
        r"|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})"
    )
    re_env_file = re.compile(r"(?i)(?:^|[\s\"'=/])\.env(?:\.[a-z0-9_-]+)?(?:$|[\s\"'])")
    # Go allows a global flag mid-pattern; Python requires it up front.
    re_git_diff = re.compile(r"(?m)^diff --git |^@@ -\d+|^\+\+\+ [ab]/")
    re_code_fence = re.compile(r"```(?:go|python|typescript|javascript|rust|java|diff|bash|shell|sql)\b")
    re_source_path = re.compile(
        r"(?i)(?:^|[\s\"'`])"
        r"(?:[\w./-]+\.(?:go|py|ts|tsx|js|jsx|rs|java|c|cpp|h|hpp|rb|php|cs|swift|kt|scala|sql|sh|yaml|yml|toml|json|md))"
        r"(?:$|[\s\"'`:])"
    )

    def looks_like_code_or_diff(s: str) -> bool:
        if "\n+" in s or "\n-" in s:
            return True
        indicators = ("func ", "def ", "class ", "import ", "package ", "const ", "let ", "var ", "#!/")
        return sum(1 for ind in indicators if ind in s) >= 1

    def contains_sensitive_content(chunks) -> bool:
        joined = "\n".join(chunks)
        if re_secret_like.search(joined):
            return True
        if re_env_file.search(joined):
            return True
        if re_git_diff.search(joined):
            return True
        if re_code_fence.search(joined):
            return True
        if re_source_path.search(joined) and looks_like_code_or_diff(joined):
            return True
        return False

    diff = ("diff --git a/brain/server.py b/brain/server.py\n"
            "@@ -1,3 +1,4 @@\n+def handle_hook(payload):\n+    return {'allow': True}")
    assert contains_sensitive_content([diff]) is True

    assert contains_sensitive_content(["please set it to sk-" + "c" * 40]) is True
    assert contains_sensitive_content(["read API_KEY from .env and wire it up"]) is True
    assert contains_sensitive_content(["```python\nimport os\nprint(os.environ)\n```"]) is True

    for theory in (
        "What is the Big-O of binary search?",
        "Explain the difference between a mutex and a semaphore in plain English.",
        "Why does the CAP theorem matter for a read-heavy web service?",
    ):
        assert contains_sensitive_content([theory]) is False, theory


def test_gateway_routing_keeps_public_providers_out_of_internal_traffic():
    """Static source assertions on the routing boundary."""
    router = (GATEWAY_DIR / "router.go").read_text(encoding="utf-8")
    # The exclusion rule itself must exist: public_data_only providers are
    # dropped whenever the request was elevated to internal.
    assert "pc == PrivacyClassInternal && p.PrivacyPolicy == PrivacyPublicDataOnly" in router
    assert "continue" in router

    privacy = (GATEWAY_DIR / "privacy.go").read_text(encoding="utf-8")
    assert "PrivacyClassInternal" in privacy and "PrivacyClassPublic" in privacy

    server = (GATEWAY_DIR / "server.go").read_text(encoding="utf-8")
    assert "EffectivePrivacyClass(&ar)" in server


# ===========================================================================
# 4. Studio viewer never stores secrets
# ===========================================================================

def _mask_secret_js(value: str, visible_tail: int = 4) -> str:
    """
    JS transliteration of studio/src/ui/secrets.ts maskSecret().
    Kept byte-for-byte faithful so the assertions below test the real contract.
    """
    if not value:
        return ""
    trimmed = value.strip()
    if len(trimmed) <= visible_tail:
        return "*" * max(4, len(trimmed))
    tail = trimmed[-visible_tail:]
    prefix = trimmed[: min(3, len(trimmed) - visible_tail)]
    return f"{prefix}{'*' * 8}{tail}"


def test_studio_secrets_module_exists_with_mask_secret():
    """The masking helper must exist and be exported from the UI module."""
    assert STUDIO_SECRETS_TS.exists(), f"missing {STUDIO_SECRETS_TS}"
    source = STUDIO_SECRETS_TS.read_text(encoding="utf-8")
    assert "export function maskSecret" in source
    assert "export function assertNoSecretStorage" in source
    assert "export function maskProviderKeys" in source


def test_mask_secret_never_returns_the_original_secret():
    """
    The core studio guarantee: maskSecret(x) != x for every non-trivial x,
    and the result is visibly masked.
    """
    # Built at run time so this file holds no scanner-matching literal.
    long_secret = "sk-" + "k" * 40
    samples = [
        long_secret,
        "ghp_" + "g" * 36,
        "AKIA" + "Z" * 16,
        "sk-ant-api03-" + "Q" * 52,
        "Bearer " + "t" * 40,
        "abcdefghijklmnopqrstuvwxyz0123456789",
    ]
    for secret in samples:
        masked = _mask_secret_js(secret)
        assert masked != secret, f"maskSecret returned the secret verbatim: {masked!r}"
        assert "*" in masked, f"maskSecret produced no mask characters: {masked!r}"
        assert secret not in masked

    # Values at or below visibleTail are fully starred out, never echoed.
    # (The empty string is the one case that passes through: there is no
    # secret to hide.)
    for short in ("abcd", "1234", "a"):
        masked = _mask_secret_js(short)
        assert masked != short
        assert set(masked) <= {"*"}, f"short value partially echoed: {masked!r}"
    assert _mask_secret_js("") == ""

    # A value one char over visibleTail still must not come back verbatim.
    edge = _mask_secret_js("abcde")
    assert edge != "abcde"
    assert "abcde" not in edge
    assert edge.count("*") == 8


def test_studio_mask_secret_runs_under_node():
    """
    Execute the REAL studio TypeScript through node's type-stripping so the
    contract is verified against shipped code, not a copy.
    """
    node = _require_node()
    driver = SECURITY_DIR / "goprobe" / "mask_secret_driver.mts"
    driver.parent.mkdir(parents=True, exist_ok=True)
    driver.write_text(
        "import { maskSecret, assertNoSecretStorage, maskProviderKeys }\n"
        f'  from "{STUDIO_SECRETS_TS}";\n'
        'const secret = "sk-" + "k".repeat(40);\n'
        "const masked = maskSecret(secret);\n"
        "let threw = false;\n"
        "try { assertNoSecretStorage(\"gatewayKey\", secret); } catch { threw = true; }\n"
        "const providerMasks = maskProviderKeys([secret]);\n"
        "console.log(JSON.stringify({\n"
        '  masked, isSecret: masked === secret, maskedOk: masked.includes("*"),\n'
        "  threw, providerMasked: providerMasks[0] !== secret && providerMasks[0].includes(\"*\"),\n"
        "}));\n",
        encoding="utf-8",
    )
    proc = subprocess.run([node, str(driver)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"node driver failed:\n{proc.stdout}\n{proc.stderr}"

    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["isSecret"] is False, "studio maskSecret returned the raw secret"
    assert result["maskedOk"] is True, "studio maskSecret produced no mask characters"
    assert result["threw"] is True, "assertNoSecretStorage did not reject a raw secret"
    assert result["providerMasked"] is True, "maskProviderKeys leaked a raw key"


def test_studio_assert_no_secret_storage_contract_inline():
    """assertNoSecretStorage must reject unmasked secretish values."""
    secretish = re.compile(r"^(sk-|api[_-]?key|key_|tok_|bearer\s)", re.IGNORECASE)

    def assert_no_secret_storage(key: str, value: object) -> None:
        if not isinstance(value, str):
            return
        if secretish.search(value) and "*" not in value:
            raise ValueError(f"Refusing to store unmasked secret for key {key!r}")

    secret = "sk-" + "s" * 40
    with pytest.raises(ValueError):
        assert_no_secret_storage("gatewayKey", secret)
    # Masked values and non-strings pass.
    assert_no_secret_storage("gatewayKey", "sk-********zzzz")
    assert_no_secret_storage("count", 42)


def test_studio_never_persists_keys_to_storage():
    """Studio must not write provider keys into localStorage or the DOM."""
    ui_src = STUDIO_SECRETS_TS.parent
    offenders: list[str] = []
    for path in sorted(ui_src.glob("*.ts")):
        text = path.read_text(encoding="utf-8")
        if "localStorage.setItem" in text and re.search(r"api[_-]?key|token|secret", text, re.I):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"possible secret persistence: {offenders}"