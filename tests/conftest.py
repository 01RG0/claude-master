"""tests/conftest.py — Global test isolation and safety fixtures."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
import pytest


def _sha256(path: Path) -> str:
    """Compute SHA256 hex digest of path, or empty string if it does not exist."""
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(autouse=True, scope="session")
def isolate_test_gateway_config():
    """Isolate gateway config and capabilities during test runs.

    Prevents unit/integration tests from mutating live gateway/config.json
    and gateway/capabilities.json on disk (ADR-010).
    """
    repo_root = Path(__file__).resolve().parent.parent
    src_cfg = (repo_root / "gateway" / "config.json").resolve()
    src_cap = (repo_root / "gateway" / "capabilities.json").resolve()

    # 1. Compute SHA256 of gateway/config.json and gateway/capabilities.json at session start
    start_cfg_hash = _sha256(src_cfg)
    start_cap_hash = _sha256(src_cap)

    with tempfile.TemporaryDirectory(prefix="cm-test-cfg-") as tmpdir:
        dst_cfg = (Path(tmpdir) / "config.json").resolve()
        dst_cap = (Path(tmpdir) / "capabilities.json").resolve()

        if src_cfg.exists():
            shutil.copy2(src_cfg, dst_cfg)
        else:
            dst_cfg.write_text("{}", encoding="utf-8")

        if src_cap.exists():
            shutil.copy2(src_cap, dst_cap)
        else:
            dst_cap.write_text("{}", encoding="utf-8")

        old_cfg = os.environ.get("CLAUDE_MASTER_GATEWAY_CONFIG")
        old_cap = os.environ.get("CLAUDE_MASTER_GATEWAY_CAPABILITIES")

        os.environ["CLAUDE_MASTER_GATEWAY_CONFIG"] = str(dst_cfg)
        os.environ["CLAUDE_MASTER_GATEWAY_CAPABILITIES"] = str(dst_cap)

        # Verify CLAUDE_MASTER_GATEWAY_CONFIG points to a temporary copy
        current_cfg = os.environ.get("CLAUDE_MASTER_GATEWAY_CONFIG")
        assert current_cfg is not None, "CLAUDE_MASTER_GATEWAY_CONFIG must be set"
        current_cfg_path = Path(current_cfg).resolve()
        assert current_cfg_path != src_cfg, (
            f"CLAUDE_MASTER_GATEWAY_CONFIG points to live gateway/config.json ({src_cfg}) "
            "instead of a temporary copy!"
        )
        assert current_cfg_path == dst_cfg, (
            f"CLAUDE_MASTER_GATEWAY_CONFIG ({current_cfg_path}) does not point to temporary copy ({dst_cfg})"
        )

        try:
            yield
        finally:
            teardown_cfg = os.environ.get("CLAUDE_MASTER_GATEWAY_CONFIG")
            if teardown_cfg:
                assert Path(teardown_cfg).resolve() != src_cfg, (
                    f"CLAUDE_MASTER_GATEWAY_CONFIG was pointed back to live gateway/config.json ({src_cfg}) during tests!"
                )

            if old_cfg is not None:
                os.environ["CLAUDE_MASTER_GATEWAY_CONFIG"] = old_cfg
            else:
                os.environ.pop("CLAUDE_MASTER_GATEWAY_CONFIG", None)

            if old_cap is not None:
                os.environ["CLAUDE_MASTER_GATEWAY_CAPABILITIES"] = old_cap
            else:
                os.environ.pop("CLAUDE_MASTER_GATEWAY_CAPABILITIES", None)

            # 2. At session teardown, verify hashes match. If modified, fail with a clear assertion.
            end_cfg_hash = _sha256(src_cfg)
            end_cap_hash = _sha256(src_cap)

            assert end_cfg_hash == start_cfg_hash, (
                f"STRICT SAFETY GUARD FAILURE: gateway/config.json was modified during test run! "
                f"Expected SHA256: {start_cfg_hash}, got: {end_cfg_hash}"
            )
            assert end_cap_hash == start_cap_hash, (
                f"STRICT SAFETY GUARD FAILURE: gateway/capabilities.json was modified during test run! "
                f"Expected SHA256: {start_cap_hash}, got: {end_cap_hash}"
            )


@pytest.fixture(autouse=True, scope="function")
def verify_test_gateway_config_points_to_temp():
    """Verify in every test that CLAUDE_MASTER_GATEWAY_CONFIG points to a temporary copy."""
    repo_root = Path(__file__).resolve().parent.parent
    src_cfg = (repo_root / "gateway" / "config.json").resolve()
    current = os.environ.get("CLAUDE_MASTER_GATEWAY_CONFIG")
    assert current is not None, "CLAUDE_MASTER_GATEWAY_CONFIG must be set"
    current_path = Path(current).resolve()
    assert current_path != src_cfg, (
        f"CLAUDE_MASTER_GATEWAY_CONFIG points to live gateway/config.json ({src_cfg}) instead of a temporary copy!"
    )
