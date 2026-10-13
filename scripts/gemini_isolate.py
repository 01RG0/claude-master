"""Isolate gemini 400: plain text vs image-in-tool-message."""
import json, urllib.request

def post(body):
    req = urllib.request.Request("http://localhost:8080/v1/messages",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, r.read().decode()[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:600]

# A: plain text user message
print("A plain:", post({"model":"gemini-2.5-flash","messages":[{"role":"user","content":"say hi"}],"max_tokens":16}))

# B: image in a USER message (baseline vision)
b64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
print("B user-image:", post({"model":"gemini-2.5-flash","messages":[
    {"role":"user","content":[
        {"type":"text","text":"describe"},
        {"type":"image","source":{"type":"base64","media_type":"image/png","data":b64}}]}],
    "max_tokens":32}))

# C: image inside a tool_result block (the shape under test)
print("C tool-image:", post({"model":"gemini-2.5-flash","messages":[
    {"role":"user","content":"describe"},
    {"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"read","input":{}}]},
    {"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":[
        {"type":"text","text":"screenshot.png"},
        {"type":"image","source":{"type":"base64","media_type":"image/png","data":b64}}]}]}],
    "max_tokens":32}))

# D: image inside tool_result but NO tool_use declared (no tools= in request)
print("D tool-image-no-tooluse:", post({"model":"gemini-2.5-flash","messages":[
    {"role":"user","content":"describe"},
    {"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":[
        {"type":"text","text":"screenshot.png"},
        {"type":"image","source":{"type":"base64","media_type":"image/png","data":b64}}]}]}],
    "max_tokens":32}))