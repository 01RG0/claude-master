import subprocess
import time
import os
import shutil
import json
import tempfile

tmp_dir = os.path.join(tempfile.gettempdir(), "test_claude_cli_run")
shutil.rmtree(tmp_dir, ignore_errors=True)
os.makedirs(tmp_dir, exist_ok=True)

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

work_dir = os.path.join(tmp_dir, "work")
os.makedirs(work_dir, exist_ok=True)
with open(os.path.join(work_dir, "hello.py"), "w") as f:
    f.write('print("OLD")\n')

# Start gateway
gw_exe = os.path.abspath("gateway/gateway.exe")
cfg = os.path.abspath("gateway/config.json")
gw = subprocess.Popen([gw_exe, "-config", cfg, "-listen", "127.0.0.1:8080"],
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    time.sleep(1)
    env = dict(os.environ,
               ANTHROPIC_BASE_URL="http://127.0.0.1:8080",
               ANTHROPIC_API_KEY="dummy",
               ANTHROPIC_MODEL="openai/gpt-oss-120b",
               CLAUDE_CONFIG_DIR=prof_dir)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    cmd = ["claude", "-p", "Edit hello.py to print('NEW')", "--allowedTools", "Edit", "Read", "Write", "--add-dir", work_dir]
    t0 = time.time()
    res = subprocess.run(cmd, cwd=work_dir, env=env, capture_output=True, text=True, timeout=60)
    dt = time.time() - t0
    print(f"RC: {res.returncode} in {dt:.2f}s")
    print("STDOUT:\n", res.stdout[:500])
    print("STDERR:\n", res.stderr[:500])
    with open(os.path.join(work_dir, "hello.py")) as f:
        print("FILE CONTENT:", repr(f.read()))
finally:
    gw.terminate()
    try:
        out, _ = gw.communicate(timeout=2)
        print("GATEWAY LOG:\n", out[:500])
    except:
        gw.kill()
