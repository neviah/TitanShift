"""Prompt test script that verifies a file-edit prompt end-to-end."""
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
WORKSPACE_ROOT = "D:/Projects/TemporaryWorkspaces/01"
TARGET_FILE = Path("D:/Projects/TemporaryWorkspaces/01/snack-store-landing/style.css")

PROMPT = (
    "Open snack-store-landing/style.css and read its contents. "
    "Then improve the CSS by: "
    "1) Make nav sticky with position: sticky, top: 0, z-index: 100, and backdrop-filter blur. "
    "2) Add a dark overlay gradient to the .hero section. "
    "3) Improve the .btn hover state with a smooth transition. "
    "Write the updated CSS back to snack-store-landing/style.css."
)


def main() -> None:
    before = TARGET_FILE.stat().st_mtime if TARGET_FILE.exists() else 0

    with httpx.Client(timeout=180) as client:
        root_set = client.post(f"{BASE}/workspace/set-root", json={"path": WORKSPACE_ROOT})
        print("Set workspace root:", root_set.status_code, root_set.text)

        payload = {
            "prompt": PROMPT,
            "workflow_mode": "lightning",
        }
        print("\nSubmitting task...")
        print(f"Prompt: {PROMPT[:120]}...")
        response = client.post(f"{BASE}/chat", json=payload)
        data = response.json()

    after = TARGET_FILE.stat().st_mtime if TARGET_FILE.exists() else 0

    print(f"\nStatus code: {response.status_code}")
    print(f"Success: {data.get('success')}")
    print(f"Mode: {data.get('mode')}")
    print(f"Workflow mode: {data.get('workflow_mode')}")
    print(f"Model: {data.get('model')}")
    print(f"Task ID: {data.get('task_id')}")
    print(f"Error: {data.get('error')}")
    print("File modified:", after > before)
    print("\nFull response:")
    print(data.get("response", "(no response)"))


if __name__ == "__main__":
    main()
