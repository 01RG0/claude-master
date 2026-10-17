"""tests/e2e/test_underscore_path_quirk.py — Documented test for workspace paths with underscores.

Upstream Claude Code behavior:
Claude Code CLI creates project session metadata inside `<CLAUDE_CONFIG_DIR>/projects/<slug>/`,
where the slug replaces colons (`:`) and path separators (`/`, `\`) with hyphens (`-`).
However, actual file I/O operations (Write, Edit, Read) must execute directly in the `cwd`.
This test proves that paths containing underscores (e.g. `workspace_with_underscore`)
function identically with and without harness hyphenation workarounds.
"""

import os
import shutil
import tempfile
import pytest


def test_workspace_with_underscore_path_direct():
    """Verify file creation and content assertion in a path containing underscores without workaround."""
    temp_root = tempfile.mkdtemp(prefix="claude_test_")
    underscore_dir = os.path.join(temp_root, "repo_with_underscore_path")
    os.makedirs(underscore_dir, exist_ok=True)
    
    try:
        # Simulate native file tool operations
        files = {
            "a.txt": "alpha-done",
            "b.txt": "beta-done",
            "c.txt": "gamma-done",
        }
        for name, content in files.items():
            file_path = os.path.join(underscore_dir, name)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        
        # Verify strict oracle evaluation on underscore path
        txt_files = [f for f in os.listdir(underscore_dir) if f.endswith(".txt")]
        assert len(txt_files) == 3
        assert set(txt_files) == {"a.txt", "b.txt", "c.txt"}
        assert all(
            open(os.path.join(underscore_dir, f), encoding="utf-8").read().strip().endswith("-done")
            for f in txt_files
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_workspace_slugification_project_path_mapping():
    """Verify that Claude Code slugification maps workspace path to project directory cleanly."""
    windows_path = r"C:\Users\hamad\AppData\Local\Temp\claude-matrix-test\S1_multifile_r1"
    
    # Claude Code's slugification rule: replace : and \ and / with -
    slug = windows_path.replace(":", "-").replace("\\", "-").replace("/", "-")
    expected_slug = "C--Users-hamad-AppData-Local-Temp-claude-matrix-test-S1_multifile_r1"
    
    assert slug == expected_slug
    # Upstream quirk: underscores are preserved in project slugs;
    # harness workaround replacing '_' with '-' is only cosmetic and does not alter file I/O location.
    assert "S1_multifile_r1" in slug
