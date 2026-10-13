"""Probe gemini's OpenAI-compatible endpoint directly with the shape the gateway emits."""
import json, os, urllib.request

KEY = open(os.path.join(r"D:\pRoG\claude-master", ".env")).read().split("GEMINI_API_KEY=")[1].split("\n")[0].strip()
URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

def post(body):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, r.read().decode()[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:600]

# A: plain
print("A plain:", post({"model":"gemini-2.5-flash","messages":[{"role":"user","content":"say hi"}],"max_tokens":16}))

# B: image in user message (OpenAI shape)
print("B user-image:", post({"model":"gemini-2.5-flash","messages":[
    {"role":"user","content":[
        {"type":"text","text":"describe"},
        {"type":"image_url","image_url":{"url":f"data:image/png;base64,{b64}"}}]}],
    "max_tokens":32}))

# C: tool message with image parts (what the gateway emits)
print("C tool-image:", post({"model":"gemini-2.5-flash","messages":[
    {"role":"user","content":"describe"},
    {"role":"assistant","content":None,"tool_calls":[{"id":"t1","type":"function","function":{"name":"read","arguments":"{}"}}]},
    {"role":"tool","tool_call_id":"t1","content":[
        {"type":"text","text":"screenshot.png"},
        {"type":"image_url","image_url":{"url":f"data:image/png;base64,{b64}"}}]}],
    "max_tokens":32}))

# D: tool message with STRING content (fallback)
print("D tool-string:", post({"model":"gemini-2.5-flash","messages":[
    {"role":"user","content":"describe"},
    {"role":"assistant","content":None,"tool_calls":[{"id":"t1","type":"function","function":{"name":"read","arguments":"{}"}}]},
    {"role":"tool","tool_call_id":"t1","content":"screenshot.png"}],
    "max_tokens":32}))