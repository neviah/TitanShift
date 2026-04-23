import httpx
import time

BASE = "http://127.0.0.1:8000"
TASK_ID = "d83c48cd-9f2b-4745-bd7d-375d13f9d191"

print(f"Polling task {TASK_ID}...")
for i in range(60):
    detail = httpx.get(f"{BASE}/tasks/{TASK_ID}", timeout=15).json()
    success = detail.get("success")
    status = detail.get("status")
    out = detail.get("output", {})

    print(f"  [{i*5}s] status={status} success={success}")
    if status in ("completed", "failed", "done", "error") or success is not None:
        print()
        print("=== FINAL RESULT ===")
        print(f"Success: {success}")
        print(f"Status: {status}")
        print(f"Used tools: {out.get('used_tools', [])}")
        print(f"Created paths: {out.get('created_paths', [])}")
        print(f"Updated paths: {out.get('updated_paths', [])}")
        review = out.get("review_result", {})
        if review:
            for tr in review.get("task_results", []):
                print(f"  Task: {tr.get('task')}")
                print(f"  verification_passed: {tr.get('verification_passed')}")
                feedback = str(tr.get("verification_feedback", ""))
                print(f"  verification_feedback: {feedback[:500]}")
        response = detail.get("response", "") or out.get("response", "")
        print(f"Response (tail): {str(response)[-600:]}")
        break
    time.sleep(5)
else:
    print("Timed out waiting for task completion")
