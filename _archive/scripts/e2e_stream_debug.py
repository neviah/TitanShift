from __future__ import annotations

import json
from pathlib import Path

import httpx


BASE = "http://127.0.0.1:8000"
WORKSPACE = Path(r"D:\Projects\TemporaryWorkspaces\01")

PAYLOAD = {
    "prompt": (
        "in our workspace, is a folder named emutalk-blog. the index.html is not complete "
        "and i would love for you to complete this blog-style website, complete with a "
        "style.css. use your svg tools, and other skills to improve the ui ux design. "
        "Make it modern, flashy, and amazing. in shorts, it's a blog site themed around Emus."
    ),
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


def main() -> None:
    switch_response = httpx.post(
        f"{BASE}/workspace/set-root",
        json={"path": str(WORKSPACE)},
        timeout=20,
    )
    switch_response.raise_for_status()
    print(f"workspace={switch_response.json()}")

    with httpx.stream(
        "POST",
        f"{BASE}/chat/stream",
        json=PAYLOAD,
        timeout=900,
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith("event:"):
                print(line)
                continue
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                print(f"data: {body}")
                continue
            print(json.dumps(parsed, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()