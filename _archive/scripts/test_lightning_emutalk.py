#!/usr/bin/env python3
"""Test Lightning mode with exact emutalk-blog prompt."""
from pathlib import Path
import sys

import httpx


BASE = "http://127.0.0.1:8000"
WORKSPACE = Path(r"D:\Projects\TemporaryWorkspaces\01")
TARGET_DIR = WORKSPACE / "emutalk-blog"
INDEX_HTML = TARGET_DIR / "index.html"
STYLE_CSS = TARGET_DIR / "style.css"

PROMPT = (
    "in our workspace, is a folder named emutalk-blog. the index.html is not complete "
    "and i would love for you to complete this blog-style website, complete with a "
    "style.css. use your svg tools, and other skills to improve the ui ux design. "
    "Make it modern, flashy, and amazing. in shorts, it's a blog site themed around Emus."
)

# Lightning mode payload - simpler, no orchestration
PAYLOAD = {
    "prompt": PROMPT,
    "workflow_mode": "lightning",  # NOT superpowered
    "model_backend": "openai_compatible",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


print("=" * 60)
print("LIGHTNING MODE TEST: emutalk-blog website completion")
print("=" * 60)

before_index = read_text(INDEX_HTML)
before_style = read_text(STYLE_CSS)

print(f"\n[1] Switching workspace root to: {WORKSPACE}")
switch_response = httpx.post(
    f"{BASE}/workspace/set-root",
    json={"path": str(WORKSPACE)},
    timeout=20,
)
switch_response.raise_for_status()
print(f"    ✓ Workspace switched")

print(f"\n[2] Submitting prompt in LIGHTNING mode...")
response = httpx.post(f"{BASE}/chat", json=PAYLOAD, timeout=900)
response.raise_for_status()
body = response.json()

success = body.get("success")
mode = body.get("mode")
error = body.get("error")
reply = str(body.get("response", ""))

print(f"    ✓ Response received")

after_index = read_text(INDEX_HTML)
after_style = read_text(STYLE_CSS)

index_changed = after_index != before_index
style_changed = after_style != before_style

print(f"\n[3] Results:")
print(f"    Success: {success}")
print(f"    Mode: {mode}")
print(f"    Error: {error or '(none)'}")
print(f"    Response length: {len(reply)}")

print(f"\n[4] File Status:")
print(f"    index.html exists: {INDEX_HTML.exists()} | changed: {index_changed} | size: {len(after_index)} bytes")
print(f"    style.css exists: {STYLE_CSS.exists()} | changed: {style_changed} | size: {len(after_style)} bytes")

print(f"\n[5] Content Preview:")
if after_index:
    snippet = after_index[:300].replace("\n", " ")
    print(f"    index.html: {snippet}...")
if after_style:
    snippet = after_style[:300].replace("\n", " ")
    print(f"    style.css: {snippet}...")

acceptable = (
    success is True
    and INDEX_HTML.exists()
    and STYLE_CSS.exists()
    and len(after_index.strip()) > 500
    and len(after_style.strip()) > 500
    and (index_changed or style_changed)
)

print(f"\n{'=' * 60}")
if acceptable:
    print("✓ ACCEPTABLE RESULT - Lightning mode works!")
    print("=" * 60)
    sys.exit(0)
else:
    print("✗ UNACCEPTABLE - Files not created or too small")
    print("=" * 60)
    print("\nDiagnostics:")
    if not success:
        print(f"  - success is {success}, not True")
    if not INDEX_HTML.exists():
        print(f"  - index.html does not exist")
    if not STYLE_CSS.exists():
        print(f"  - style.css does not exist")
    if len(after_index.strip()) <= 500:
        print(f"  - index.html too small ({len(after_index)} bytes)")
    if len(after_style.strip()) <= 500:
        print(f"  - style.css too small ({len(after_style)} bytes)")
    if not (index_changed or style_changed):
        print(f"  - no file changes detected")
    sys.exit(1)
