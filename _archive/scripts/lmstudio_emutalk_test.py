from pathlib import Path
import time
import httpx

BASE = "http://127.0.0.1:8000"
ROOT = Path("D:/Projects/TemporaryWorkspaces/01/emutalk-blog")


def main() -> None:
    started = time.time()
    payload = {
        "prompt": (
            "Create a flashy react blog website with fake content posts, menus, and theme selection. "
            "Call the site EmuTalk. Create a new folder emutalk-blog in the workspace and place files there."
        ),
        "workflow_mode": "superpowered",
        "spec_approved": True,
        "plan_approved": True,
    }

    with httpx.Client(timeout=1200) as client:
        root_set = client.post(f"{BASE}/workspace/set-root", json={"path": "D:/Projects/TemporaryWorkspaces/01"})
        print("set_root_status", root_set.status_code)
        response = client.post(f"{BASE}/chat", json=payload)
        data = response.json()

    print("status_code", response.status_code)
    print("elapsed_seconds", round(time.time() - started, 2))
    print("success", data.get("success"))
    print("mode", data.get("mode"))
    print("workflow", data.get("workflow_mode"))
    print("error", data.get("error"))
    print("response_preview", str(data.get("response", ""))[:900].replace("\n", " "))
    print("folder_exists", ROOT.exists())

    if ROOT.exists():
        files = sorted([p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()])
        print("file_count", len(files))
        print("files", files[:25])


if __name__ == "__main__":
    main()
