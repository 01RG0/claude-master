"""Live vision probe: does a real provider accept an image part INSIDE a tool message?

The gateway translates Claude tool_result blocks (with embedded image blocks) into
OpenAI tool messages whose content is an array of parts including image_url. Gemini's
OpenAI endpoint 400s on that shape, so the adapter must downgrade it to a text
placeholder. This hits gemini-2.5-flash through the gateway and reports status.
"""
import json, os, subprocess, sys, time, urllib.request

REPO = r"D:\pRoG\claude-master"
GW = os.path.join(REPO, "gateway", "gateway.exe")
CFG = os.path.join(REPO, "gateway", "config.json")
GATEWAY_URL = "http://localhost:8080"


def wait(url, timeout=30):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    env = dict(os.environ)
    env["GEMINI_API_KEY"] = open(os.path.join(REPO, ".env")).read().split("GEMINI_API_KEY=")[1].split("\n")[0].strip()
    env["ANTHROPIC_BASE_URL"] = GATEWAY_URL
    env["ANTHROPIC_API_KEY"] = "dummy"
    env["ANTHROPIC_MODEL"] = "sonnet"

    log = open(os.path.join(os.environ.get("TEMP", "/tmp"), "vision_probe_gw.log"), "w", buffering=1)
    gw = subprocess.Popen([GW, "--config", CFG, "--log-requests", "off"],
                          cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        if not wait(f"{GATEWAY_URL}/health"):
            print("FAIL: gateway did not come up"); return 2
        b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        body = json.dumps({
            "model": "gemini-2.5-flash",
            "messages": [
                {"role": "user", "content": "Describe this image in one sentence."},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "read", "input": {}}]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": [
                        {"type": "text", "text": "screenshot.png"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}
                    ]}
                ]},
            ],
            "max_tokens": 64,
        }).encode()
        req = urllib.request.Request(f"{GATEWAY_URL}/v1/messages", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read().decode("utf-8", "replace")
                print(f"PASS status={r.status} body={data[:300]!r}")
                return 0
        except urllib.error.HTTPError as e:
            print(f"FAIL HTTP {e.code}: {e.read().decode('utf-8','replace')[:400]!r}")
            return 1
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except Exception:
            gw.kill()


if __name__ == "__main__":
    sys.exit(main())