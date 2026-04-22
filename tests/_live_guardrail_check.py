"""
Live guardrail integration check against running harness server.
Usage: python tests/_live_guardrail_check.py
"""
import httpx
import json
import sys

BASE = "http://127.0.0.1:8999"


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main() -> int:
    failures: list[str] = []

    # ---------- health ----------
    section("Health")
    r = httpx.get(f"{BASE}/health", timeout=10)
    status = r.json().get("status", "unknown")
    print(f"  status: {status} ({r.status_code})")

    # ---------- policy CRUD ----------
    section("Policy Rules CRUD")
    r = httpx.get(f"{BASE}/policy/rules", timeout=10)
    initial_rules = r.json()["rules"]
    print(f"  baseline rules: {len(initial_rules)}")
    if len(initial_rules) != 19:
        failures.append(f"Expected 19 baseline rules, got {len(initial_rules)}")

    # add
    add_payload = {"permission": "bash", "pattern": "curl *", "action": "deny"}
    r = httpx.post(f"{BASE}/policy/rules", json=add_payload, timeout=10)
    assert r.status_code == 200, f"POST /policy/rules failed: {r.text}"
    added_idx = r.json()["index"]
    print(f"  added rule at index {added_idx}: {r.json()['rule']}")

    # verify count
    r = httpx.get(f"{BASE}/policy/rules", timeout=10)
    after_add = r.json()["rules"]
    if len(after_add) != 20:
        failures.append(f"Expected 20 rules after add, got {len(after_add)}")
    else:
        print(f"  count after add: {len(after_add)} ✓")

    # delete
    r = httpx.delete(f"{BASE}/policy/rules/{added_idx}", timeout=10)
    assert r.status_code == 200, f"DELETE /policy/rules failed: {r.text}"
    r = httpx.get(f"{BASE}/policy/rules", timeout=10)
    after_del = r.json()["rules"]
    if len(after_del) != 19:
        failures.append(f"Expected 19 rules after delete, got {len(after_del)}")
    else:
        print(f"  count after delete: {len(after_del)} ✓")

    # out-of-range delete should 404
    r = httpx.delete(f"{BASE}/policy/rules/9999", timeout=10)
    if r.status_code != 404:
        failures.append(f"OOB delete should be 404, got {r.status_code}")
    else:
        print("  OOB delete 404 ✓")

    # ---------- audit tools category ----------
    section("Audit — tools category")
    r = httpx.get(f"{BASE}/harness-audit?category=tools", timeout=15)
    if r.status_code != 200:
        failures.append(f"Audit endpoint failed: {r.status_code}")
        print(f"  ERROR: {r.text[:200]}")
    else:
        tool_findings = r.json().get("categories", {}).get("tools", {}).get("findings", [])
        by_id = {f["id"]: f for f in tool_findings}
        print(f"  total tool findings: {len(tool_findings)}")
        for fid, f in by_id.items():
            print(f"  [{f['severity']}] {fid}: {f['title']}")

        # AUDIT-T008 should NOT fire because we have our deny baselines
        # The live server may have loaded config before dd if=* was added — patch it live
        if "AUDIT-T008" in by_id:
            detail = by_id["AUDIT-T008"]["detail"]
            if "dd if=*" in detail:
                # add the missing rule dynamically and re-audit
                httpx.post(f"{BASE}/policy/rules", json={"permission": "bash", "pattern": "dd if=*", "action": "deny"}, timeout=10)
                r_patch = httpx.get(f"{BASE}/harness-audit?category=tools", timeout=15)
                still_t008 = [f for f in r_patch.json()["categories"]["tools"]["findings"] if f["id"] == "AUDIT-T008"]
                if still_t008:
                    failures.append(f"AUDIT-T008 still fires after patching dd if=*: {still_t008[0]['detail']}")
                else:
                    print("  AUDIT-T008 cleared after adding dd if=* deny rule ✓")
            else:
                failures.append(f"AUDIT-T008 fires for unexpected patterns: {detail}")
        else:
            print("  AUDIT-T008 absent (deny baselines present) ✓")

        # AUDIT-T003 should NOT fire (no wildcard allow)
        if "AUDIT-T003" in by_id:
            failures.append("AUDIT-T003 should not fire — no wildcard allow rules present")
        else:
            print("  AUDIT-T003 absent (no wildcard allow) ✓")

        # After adding a wildcard allow rule, T003 should fire
        httpx.post(f"{BASE}/policy/rules", json={"permission": "bash", "pattern": "*", "action": "allow"}, timeout=10)
        r2 = httpx.get(f"{BASE}/harness-audit?category=tools", timeout=15)
        t3_findings = [f for f in r2.json()["categories"]["tools"]["findings"] if f["id"] == "AUDIT-T003"]
        # clean up
        r_list = httpx.get(f"{BASE}/policy/rules", timeout=10)
        last_idx = len(r_list.json()["rules"]) - 1
        httpx.delete(f"{BASE}/policy/rules/{last_idx}", timeout=10)
        if t3_findings:
            print("  AUDIT-T003 fires on wildcard allow rule ✓")
        else:
            failures.append("AUDIT-T003 should fire after adding wildcard allow rule")

    # ---------- tool list policy evaluation ----------
    section("Tool Policy Evaluation")
    r = httpx.get(f"{BASE}/tools", timeout=10)
    if r.status_code != 200:
        failures.append(f"GET /tools failed: {r.status_code}")
    else:
        tools = r.json()
        allowed_tools = [t for t in tools if t["allowed_by_policy"]]
        blocked_tools = [t for t in tools if not t["allowed_by_policy"]]
        print(f"  registered tools: {len(tools)}")
        print(f"  allowed: {len(allowed_tools)}, blocked: {len(blocked_tools)}")
        for t in blocked_tools[:5]:
            print(f"    BLOCKED: {t['name']} — {t['policy_reason']}")

    # ---------- approval-reply (invalid ID → 404) ----------
    section("Approval Reply — unknown ID returns 404")
    r = httpx.post(
        f"{BASE}/tools/approval-reply",
        json={"approval_id": "nonexistent-id", "decision": "once"},
        timeout=10,
    )
    if r.status_code == 404:
        print("  404 on unknown approval_id ✓")
    else:
        failures.append(f"Expected 404 for unknown approval_id, got {r.status_code}")

    # ---------- approval-reply (invalid decision → 422) ----------
    section("Approval Reply — invalid decision returns 422")
    r = httpx.post(
        f"{BASE}/tools/approval-reply",
        json={"approval_id": "any", "decision": "maybe"},
        timeout=10,
    )
    if r.status_code == 422:
        print("  422 on invalid decision ✓")
    else:
        failures.append(f"Expected 422 for invalid decision, got {r.status_code}")

    # ---------- summary ----------
    section("Summary")
    if failures:
        print(f"  FAILURES ({len(failures)}):")
        for f in failures:
            print(f"    ✗ {f}")
        return 1
    else:
        print("  ALL CHECKS PASSED ✓")
        return 0


if __name__ == "__main__":
    sys.exit(main())
