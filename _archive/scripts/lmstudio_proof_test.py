from pathlib import Path
import httpx

BASE = "http://127.0.0.1:8000"
TARGET = Path("D:/Projects/TemporaryWorkspaces/01/timeout-proof/index.html")


def main() -> None:
    before_exists = TARGET.exists()
    before_mtime = TARGET.stat().st_mtime if before_exists else 0.0

    payload = {
        "prompt": (
            "In workspace folder timeout-proof, create or update index.html with a simple page "
            "title 'Timeout Proof' and an h1 'LM Studio completed this run'. "
            "Keep it minimal and valid HTML."
        ),
        "workflow_mode": "superpowered",
        "spec_approved": True,
        "plan_approved": True,
    }

    response = httpx.post(f"{BASE}/chat", json=payload, timeout=420)
    data = response.json()

    after_exists = TARGET.exists()
    after_mtime = TARGET.stat().st_mtime if after_exists else 0.0

    print("status_code", response.status_code)
    print("success", data.get("success"))
    print("mode", data.get("mode"))
    print("workflow", data.get("workflow_mode"))
    print("error", data.get("error"))
    print("response_preview", str(data.get("response", ""))[:700].replace("\n", " "))
    print("file_exists", after_exists)
    print("file_changed", after_exists and (not before_exists or after_mtime > before_mtime))

    if after_exists:
        content = TARGET.read_text(encoding="utf-8", errors="ignore")
        print("contains_timeout_proof", "Timeout Proof" in content)
        print("contains_h1", "LM Studio completed this run" in content)


if __name__ == "__main__":
    main()
