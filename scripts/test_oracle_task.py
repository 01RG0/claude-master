import os
import shutil
import subprocess
import tempfile
import time
import json

tmp_dir = os.path.join(tempfile.gettempdir(), "test_oracle_task")
shutil.rmtree(tmp_dir, ignore_errors=True)
os.makedirs(tmp_dir, exist_ok=True)

# Write buggy function and pytest test
with open(os.path.join(tmp_dir, "algo.py"), "w") as f:
    f.write('''def is_palindrome(s: str) -> bool:
    # Buggy: does not ignore case and spaces
    return s == s[::-1]
''')

with open(os.path.join(tmp_dir, "test_algo.py"), "w") as f:
    f.write('''import pytest
from algo import is_palindrome

def test_palindrome_simple():
    assert is_palindrome("radar") is True
    assert is_palindrome("hello") is False

def test_palindrome_case_and_spaces():
    assert is_palindrome("A man a plan a canal Panama") is True
    assert is_palindrome("Was it a car or a cat I saw") is True
''')

# Start gateway
gw_exe = os.path.abspath("gateway/gateway.exe")
cfg = os.path.abspath("gateway/config.json")
gw = subprocess.Popen([gw_exe, "-config", cfg, "-listen", "127.0.0.1:8080"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(1)
    prof_dir = os.path.join(tmp_dir, "prof")
    os.makedirs(prof_dir, exist_ok=True)
    with open(os.path.join(prof_dir, "settings.json"), "w") as f:
        json.dump({
            "env": {
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:8080",
                "ANTHROPIC_API_KEY": "dummy",
                "ANTHROPIC_MODEL": "openai/gpt-oss-120b"
            }
        }, f)

    env = dict(os.environ,
               ANTHROPIC_BASE_URL="http://127.0.0.1:8080",
               ANTHROPIC_API_KEY="dummy",
               ANTHROPIC_MODEL="openai/gpt-oss-120b",
               CLAUDE_CONFIG_DIR=prof_dir)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    
    cmd = ["claude", "-p", "Fix is_palindrome in algo.py so it ignores case and non-alphanumeric characters. Run pytest test_algo.py to verify.",
           "--allowedTools", "Edit", "Read", "Write", "Bash", "--add-dir", tmp_dir]
    t0 = time.perf_counter()
    res = subprocess.run(cmd, cwd=tmp_dir, env=env, capture_output=True, text=True, timeout=90)
    wall_s = time.perf_counter() - t0
    
    # Run independent oracle:
    oracle_res = subprocess.run(["pytest", "test_algo.py"], cwd=tmp_dir, capture_output=True, text=True)
    oracle_pass = (oracle_res.returncode == 0)
    
    print(f"CLI RC={res.returncode}, WallClock={wall_s:.2f}s, OraclePass={oracle_pass}")
    print("Oracle Output:\n", oracle_res.stdout)
finally:
    gw.terminate()
