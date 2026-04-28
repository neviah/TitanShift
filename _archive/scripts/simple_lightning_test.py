#!/usr/bin/env python3
"""Simple Lightning mode test with output."""
import json
from pathlib import Path
import httpx

BASE = "http://127.0.0.1:8000"
WORKSPACE = Path(r"D:\Projects\TemporaryWorkspaces\01")

PROMPT = (
    "in our workspace, is a folder named emutalk-blog. the index.html is not complete "
    "and i would love for you to complete this blog-style website, complete with a "
    "style.css. use your svg tools, and other skills to improve the ui ux design. "
    "Make it modern, flashy, and amazing. in shorts, it's a blog site themed around Emus."
)

# Simple Lightning mode
PAYLOAD = {
    "prompt": PROMPT,
    "workflow_mode": "lightning",
    "model_backend": "openai_compatible",
}

print("[1] Switch workspace...")
httpx.post(f"{BASE}/workspace/set-root", json={"path": str(WORKSPACE)}, timeout=20).raise_for_status()

print("[2] Submit Lightning prompt...")
response = httpx.post(f"{BASE}/chat", json=PAYLOAD, timeout=900)
response.raise_for_status()
body = response.json()

print(f"\n[RESULT]")
print(f"Success: {body.get('success')}")
print(f"Mode: {body.get('mode')}")
print(f"Workflow mode: {body.get('workflow_mode')}")
print(f"Error: {body.get('error')}")
print(f"Used tools: {body.get('used_tools', [])}")
print(f"Created paths: {len(body.get('created_paths', []))} files")

# Check specific files
index_path = WORKSPACE / "emutalk-blog" / "index.html"
style_path = WORKSPACE / "emutalk-blog" / "style.css"

print(f"\n[FILES]")
print(f"index.html exists: {index_path.exists()} ({len(index_path.read_text()) if index_path.exists() else 0} bytes)")
print(f"style.css exists: {style_path.exists()} ({len(style_path.read_text()) if style_path.exists() else 0} bytes)")

print(f"\n[RESPONSE] (last 500 chars)")
print(str(body.get('response', ''))[-500:])
