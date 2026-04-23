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

PAYLOAD = {
    "prompt": PROMPT,
    "workflow_mode": "superpowered",
    "model_backend": "openai_compatible",
    "spec_approved": True,
    "plan_approved": True,
    "plan_tasks": [
        {
            "title": "Complete emutalk-blog website",
            "description": (
                "Complete index.html and create style.css for the emutalk-blog folder. "
                "Use SVG artwork and improve the UI and UX design."
            ),
        }
    ],
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


before_index = read_text(INDEX_HTML)
before_style = read_text(STYLE_CSS)

print(f"Switching workspace root to: {WORKSPACE}")
switch_response = httpx.post(
    f"{BASE}/workspace/set-root",
    json={"path": str(WORKSPACE)},
    timeout=20,
)
switch_response.raise_for_status()
print(f"Workspace switch response: {switch_response.json()}")

print("Submitting exact prompt...")
response = httpx.post(f"{BASE}/chat", json=PAYLOAD, timeout=900)
response.raise_for_status()
body = response.json()

success = body.get("success")
mode = body.get("mode")
error = body.get("error")
reply = str(body.get("response", ""))

after_index = read_text(INDEX_HTML)
after_style = read_text(STYLE_CSS)

index_changed = after_index != before_index
style_changed = after_style != before_style

print(f"Success: {success}")
print(f"Mode: {mode}")
print(f"Error: {error}")
print(f"Response snippet: {reply[:800]}")
print(f"index.html exists: {INDEX_HTML.exists()} changed: {index_changed} length: {len(after_index)}")
print(f"style.css exists: {STYLE_CSS.exists()} changed: {style_changed} length: {len(after_style)}")

acceptable = (
    success is True
    and INDEX_HTML.exists()
    and STYLE_CSS.exists()
    and len(after_index.strip()) > 500
    and len(after_style.strip()) > 500
    and (index_changed or style_changed)
)

print(f"Acceptable result: {acceptable}")

if not acceptable:
    sys.exit(1)
