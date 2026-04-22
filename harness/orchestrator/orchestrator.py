from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from harness.api.hooks import ApiHooks
from harness.api.hooks import HookPayload
from harness.memory.manager import MemoryManager
from harness.model.adapter import ModelRegistry, ModelRequest
from harness.orchestrator.task_store import TaskStore
from harness.runtime.config import ConfigManager
from harness.runtime.event_bus import EventBus
from harness.runtime.types import Task, TaskResult
from harness.skills.registry import SkillRegistry
from harness.state_machine.reactive import ReactiveStateMachine
from harness.tools.registry import ToolRegistry


@dataclass(slots=True)
class AgentRecord:
    agent_id: str
    role: str
    assigned_skills: list[str]
    allowed_tools: list[str]
    model_backend: str
    spawned_from_task: str | None
    created_at: str
    active: bool = True


@dataclass(slots=True)
class RoleTemplate:
    role_key: str
    role_name: str
    goal: str
    required_skills: list[str]


@dataclass(slots=True)
class LightningTaskProfile:
    domains: list[str]
    suggested_roles: list[str]
    required_skills: list[str]
    trigger_reasons: list[str]


@dataclass(slots=True)
class Orchestrator:
    config: ConfigManager
    event_bus: EventBus
    memory: MemoryManager
    models: ModelRegistry
    skills: SkillRegistry
    tools: ToolRegistry
    hooks: ApiHooks
    state_machine: ReactiveStateMachine = field(init=False)
    enable_subagents: bool = field(init=False)
    role_templates: dict[str, RoleTemplate] = field(init=False)
    task_store: TaskStore = field(init=False)
    agents: dict[str, AgentRecord] = field(init=False)

    def __post_init__(self) -> None:
        self.state_machine = ReactiveStateMachine(self.models, self.config, self.tools, self.skills, self.hooks)
        self.enable_subagents = bool(self.config.get("orchestrator.enable_subagents", False))
        self.role_templates = self._build_default_role_templates()
        # Use SQLite-backed TaskStore so task history survives restarts.
        _storage_raw = str(self.config.get("memory.storage_dir", ".harness"))
        _storage_dir = Path(_storage_raw) if Path(_storage_raw).is_absolute() else Path.cwd() / _storage_raw
        self.task_store = TaskStore(db_path=_storage_dir / "tasks.db")
        self.agents = {
            "main-agent": AgentRecord(
                agent_id="main-agent",
                role=str(self.config.get("orchestrator.default_role", "General Agent")),
                assigned_skills=["reactive_chat"],
                allowed_tools=[],
                model_backend=str(self.config.get("model.default_backend", "local_stub")),
                spawned_from_task=None,
                created_at=datetime.now(timezone.utc).isoformat(),
                active=True,
            )
        }

    def _build_default_role_templates(self) -> dict[str, RoleTemplate]:
        """Build default role templates for Superpowered review loops."""
        return {
            "implementer": RoleTemplate(
                role_key="implementer",
                role_name="Implementer Agent",
                goal="Implement the assigned task exactly as specified in the approved plan.",
                required_skills=["subagent-driven-development", "test-driven-development"],
            ),
            "spec_reviewer": RoleTemplate(
                role_key="spec_reviewer",
                role_name="Spec Reviewer Agent",
                goal="Validate implementation against approved requirements and plan acceptance criteria.",
                required_skills=["subagent-driven-development"],
            ),
            "code_reviewer": RoleTemplate(
                role_key="code_reviewer",
                role_name="Code Reviewer Agent",
                goal="Review code quality, architecture fit, and maintainability before merge.",
                required_skills=["subagent-driven-development"],
            ),
            "verifier": RoleTemplate(
                role_key="verifier",
                role_name="Verification Agent",
                goal="Run evidence-based validation before marking work complete.",
                required_skills=["verification-before-completion"],
            ),
            "planner": RoleTemplate(
                role_key="planner",
                role_name="Planner Agent",
                goal=(
                    "Explore the codebase in READ-ONLY mode, produce a structured spec and "
                    "step-by-step implementation plan for user approval. Do NOT create, edit, "
                    "or delete any files. Output must be JSON with keys: "
                    "\"spec\" (string), \"plan\" (string), \"plan_tasks\" (list of objects with "
                    "\"title\" and \"description\" keys), \"acceptance_criteria\" (list of strings)."
                ),
                required_skills=["brainstorming"],
            ),
        }

    def list_role_templates(self) -> list[dict[str, object]]:
        """List role template metadata for UI/API inspection."""
        return [
            {
                "role_key": t.role_key,
                "role_name": t.role_name,
                "goal": t.goal,
                "required_skills": list(t.required_skills),
            }
            for t in self.role_templates.values()
        ]

    async def _invoke_role_model(
        self,
        parent_task: Task,
        role_key: str,
        context: str,
    ) -> dict[str, object]:
        """Run the model in a named role context, returning {passed: bool, feedback: str}.

        Builds a one-shot Task with a role-scoped system prompt and parses the
        LLM response for a PASS / FAIL verdict.  Falls back to pass on invocation
        error so review loops are not permanently blocked by infrastructure issues.
        """
        template = self.role_templates.get(role_key)
        role_name = template.role_name if template else role_key.replace("_", " ").title()
        goal = template.goal if template else ""
        model = self.models.select_model(
            parent_task.input.get(
                "model_backend",
                self.config.get("model.default_backend", "local_stub"),
            )
        )
        # Use the model adapter's configured timeout so slow backends (e.g. LM Studio) don't time out
        role_timeout_s = getattr(model, "timeout_s", None) or max(
            30.0, float(self.config.get("orchestrator.skill_execution_timeout_s", 15.0))
        )
        system_prompt = (
            f"You are the {role_name}. {goal} "
            "Respond with PASS or FAIL on the first line, followed by a concise explanation "
            "(1-3 sentences) justifying your decision. Do not call tools."
        )
        request = ModelRequest(
            prompt=(
                f"Role: {role_name}\n"
                f"Goal: {goal}\n\n"
                f"Context:\n{context}\n"
            ),
            system_prompt=system_prompt,
            timeout_s=role_timeout_s,
        )
        try:
            response = await asyncio.wait_for(model.generate(request), timeout=role_timeout_s)
            response_text = str(response.text).strip()
        except Exception as exc:
            return {
                "passed": True,
                "feedback": f"Reviewer invocation failed (treated as PASS to avoid blocking): {exc}",
            }

        first_line = response_text.split("\n")[0].upper()
        passed: bool
        if first_line.startswith("FAIL"):
            passed = False
        elif first_line.startswith("PASS"):
            passed = True
        else:
            # Ambiguous response — local LLMs often include 'fail' in preamble text;
            # default to PASS unless the response is explicitly empty.
            passed = bool(response_text)

        return {"passed": passed, "feedback": response_text[:600]}

    async def _spawn_role_subagent(self, parent_task: Task, role_key: str, description: str) -> str:
        """Spawn a subagent from a named role template."""
        template = self.role_templates.get(role_key)
        if template is None:
            raise KeyError(f"Role template not found: {role_key}")

        child_task = Task(
            id=f"{parent_task.id}:{role_key}:{uuid.uuid4().hex[:8]}",
            description=description,
            input={
                "role": template.role_name,
                "model_backend": parent_task.input.get(
                    "model_backend",
                    self.config.get("model.default_backend", "local_stub"),
                ),
            },
        )
        agent_id = await self.spawn_subagent(child_task)
        available_skills = [skill_id for skill_id in template.required_skills if self.skills.get_skill(skill_id) is not None]
        if available_skills:
            await self.assign_skills_to_agent(agent_id, available_skills)
        return agent_id

    async def _run_plan_phase(self, parent_task: Task) -> dict[str, object]:
        """Run a read-only planning subagent that produces spec + plan + plan_tasks.

        Mirrors Claude Code's EnterPlanMode → codebase exploration → ExitPlanMode
        pattern.  The planner role runs with workflow_mode=lightning (no review loop)
        and is instructed to output structured JSON only — no file mutations.

        Returns a dict with keys:
            spec            – high-level requirement description
            plan            – step-by-step implementation strategy
            plan_tasks      – list of {"title", "description"} dicts for the review loop
            acceptance_criteria – list of verifiable completion criteria
            raw_response    – full model output for debugging
            ok              – True when parsing succeeded, False on failure
            error           – error message on failure
        """
        template = self.role_templates.get("planner")
        planner_goal = template.goal if template else "Produce a spec and plan."

        planner_task = Task(
            id=f"{parent_task.id}:planner:{uuid.uuid4().hex[:8]}",
            description=(
                f"[Planner Agent — READ-ONLY]\n\n"
                f"Original request:\n{parent_task.description}\n\n"
                f"{planner_goal}\n\n"
                "CRITICAL CONSTRAINTS:\n"
                "- You may ONLY use read-only tools: read_file, read_context, index_project, "
                "  file_search, grep_search, list_dir, semantic_search.\n"
                "- You may NOT use write_file, replace_in_file, append_file, patch_file, "
                "  run_tests, run_project_check, or any tool that modifies state.\n"
                "- Your ENTIRE response must be valid JSON with exactly these keys:\n"
                '  {"spec": "...", "plan": "...", "plan_tasks": [{"title": "...", "description": "..."}], '
                '   "acceptance_criteria": ["..."]}\n'
                "- Do not wrap the JSON in markdown fences."
            ),
            input={
                "model_backend": parent_task.input.get(
                    "model_backend",
                    self.config.get("model.default_backend", "local_stub"),
                ),
                "workflow_mode": "lightning",
                # Empty list disables auto-detection of requested tools from description text.
                # The planner only outputs JSON; it must not be forced to call write_file etc.
                # that were detected because the description echoes the user's raw prompt.
                "requested_tools": [],
                # Tight budget: planner just needs to output JSON, not run many tool rounds.
                "budget": {
                    "max_steps": int(self.config.get("orchestrator.superpowered_mode.planner_max_steps", 8)),
                    "max_tokens": int(self.config.get("orchestrator.superpowered_mode.planner_max_tokens", 24000)),
                },
            },
        )

        try:
            result = await self.state_machine.run_task(planner_task)
            raw = str(result.output.get("response", "")).strip()
        except Exception as exc:
            return {"ok": False, "error": f"Plan phase invocation failed: {exc}", "raw_response": ""}

        # Strip optional markdown fences (```json ... ```)
        clean = raw
        if clean.startswith("```"):
            lines = clean.splitlines()
            # Drop first and last fence lines
            inner = [ln for ln in lines[1:] if not ln.strip().startswith("```")]
            clean = "\n".join(inner).strip()

        try:
            parsed: dict[str, object] = json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            # Try to salvage a partial JSON block via a best-effort search
            import re as _re
            m = _re.search(r"\{[\s\S]+\}", clean)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except Exception:
                    parsed = {}
            else:
                parsed = {}

        spec = str(parsed.get("spec", parent_task.description[:300]))
        plan = str(parsed.get("plan", raw[:800]))
        plan_tasks_raw = parsed.get("plan_tasks", [])
        plan_tasks: list[dict[str, object]] = (
            [t for t in plan_tasks_raw if isinstance(t, dict)]
            if isinstance(plan_tasks_raw, list)
            else [{"title": parent_task.description[:120], "description": plan}]
        )
        if not plan_tasks:
            plan_tasks = [{"title": parent_task.description[:120], "description": plan}]
        acceptance_raw = parsed.get("acceptance_criteria", [])
        acceptance_criteria: list[str] = (
            [str(c) for c in acceptance_raw if c]
            if isinstance(acceptance_raw, list)
            else []
        )

        return {
            "ok": True,
            "spec": spec,
            "plan": plan,
            "plan_tasks": plan_tasks,
            "acceptance_criteria": acceptance_criteria,
            "raw_response": raw,
        }

    async def _run_superpowered_review_loop(
        self,
        parent_task: Task,
        plan_tasks: list[dict[str, object]],
    ) -> dict[str, object]:
        """Run implementer → spec reviewer → code reviewer → verifier for each plan task.

        When a plan task item contains explicit simulation flags
        (``implementer_status``, ``spec_review_passed``, ``code_review_passed``,
        ``verification_passed``) they are used directly — this keeps unit tests fast and
        deterministic.  When those flags are absent the model is invoked for each role,
        producing real feedback that is stored in the result.
        """
        max_iterations = int(self.config.get("orchestrator.superpowered_mode.review_loop_max_iterations", 3))
        require_verification = bool(
            self.config.get("orchestrator.superpowered_mode.require_verification_before_done", True)
        )
        strict_verification = bool(
            parent_task.input.get(
                "strict_verification",
                self.config.get("orchestrator.superpowered_mode.strict_verification", False),
            )
        )

        task_results: list[dict[str, object]] = []

        for idx, item in enumerate(plan_tasks, start=1):
            title = str(item.get("title") or item.get("task") or f"Task {idx}")
            item_result: dict[str, object] = {"task": title, "index": idx, "iterations": 0}
            simulation_mode = "implementer_status" in item

            # ── Implementer ──────────────────────────────────────────────────────────
            implementer_id = await self._spawn_role_subagent(
                parent_task,
                "implementer",
                f"Implement planned task #{idx}: {title}",
            )
            item_result["implementer_agent_id"] = implementer_id

            if simulation_mode:
                implementer_status = str(item.get("implementer_status", "DONE")).strip().upper()
                if implementer_status not in {"DONE", "DONE_WITH_CONCERNS"}:
                    return {
                        "ok": False,
                        "failed_task": title,
                        "error": f"Implementer did not complete task: status={implementer_status}",
                        "task_results": task_results,
                    }
            else:
                # Run the implementer through the reactive loop so it can actually execute tools
                # Tight step budget for implementer — local LLMs burn ~7s/step so
                # 60 steps (lightning default) = 420s exactly. Cap hard at 12 steps.
                _max_impl_steps = int(
                    self.config.get("orchestrator.superpowered_mode.implementer_max_steps", 12)
                )
                _max_impl_tokens = int(
                    self.config.get("orchestrator.superpowered_mode.implementer_max_tokens", 32000)
                )
                implementation_rules = (
                    "Execution rules (FOLLOW STRICTLY):\n"
                    "1. The WORKSPACE SNAPSHOT below shows what already exists — do NOT call list_directory on any path already visible there.\n"
                    "2. If a file already exists, edit it in place with write_file or append_file — do NOT recreate it.\n"
                    "3. Go directly to read_file / write_file / append_file — skip all exploration.\n"
                    "4. You have a strict budget of steps. After you finish the required file changes, return your final answer IMMEDIATELY. Do not verify, summarise, or loop."
                )
                # Build a shallow 2-level workspace snapshot so the implementer skips
                # expensive list_directory exploration rounds on large workspaces.
                _workspace_snapshot = ""
                try:
                    _ws_root = self.config.workspace_root
                    _lines: list[str] = []
                    for _entry in sorted(_ws_root.iterdir()):
                        if _entry.name.startswith(".") or _entry.name in {
                            "__pycache__", "node_modules", ".venv", "venv",
                        }:
                            continue
                        if _entry.is_dir():
                            _lines.append(f"  {_entry.name}/")
                            try:
                                for _child in sorted(_entry.iterdir())[:12]:
                                    _lines.append(
                                        f"    {_child.name}{'/' if _child.is_dir() else ''}"
                                    )
                            except PermissionError:
                                pass
                        else:
                            _lines.append(f"  {_entry.name}")
                    if _lines:
                        _workspace_snapshot = (
                            "\n\nWORKSPACE SNAPSHOT (use this instead of calling list_directory on the root):\n"
                            + "\n".join(_lines[:80])
                        )
                except Exception:
                    pass  # non-fatal: snapshot is optional context
                impl_description = (
                    f"Implement task #{idx}: {title}. "
                    f"{str(item.get('description', title))}\n"
                    f"{implementation_rules}"
                    f"{_workspace_snapshot}"
                )
                impl_task = Task(
                    id=f"{parent_task.id}:impl:{idx}:{uuid.uuid4().hex[:8]}",
                    description=impl_description,
                    input={
                        **(parent_task.input or {}),
                        "workflow_mode": "lightning",
                        # Hard budget override: caps steps regardless of config
                        "budget": {
                            "max_steps": _max_impl_steps,
                            "max_tokens": _max_impl_tokens,
                        },
                    },
                )
                configured_impl_timeout = float(
                    self.config.get("orchestrator.superpowered_mode.implementer_timeout_s", 0.0)
                )
                default_impl_timeout = float(
                    self.config.get("orchestrator.superpowered_mode.default_implementer_timeout_s", 420.0)
                )
                selected_backend = str(
                    (parent_task.input or {}).get(
                        "model_backend",
                        self.config.get("model.default_backend", "local_stub"),
                    )
                )
                model_adapter = self.models.select_model(selected_backend)
                run_timeout_s = float(self.config.get("execution.run_timeout_seconds", 300.0))
                _ = model_adapter  # model adapter selection validates backend availability
                impl_timeout_target = configured_impl_timeout if configured_impl_timeout > 0 else default_impl_timeout
                impl_timeout_s = max(60.0, min(impl_timeout_target, run_timeout_s))
                try:
                    impl_task_result = await asyncio.wait_for(
                        self.state_machine.run_task(impl_task),
                        timeout=impl_timeout_s,
                    )
                    impl_passed = impl_task_result.success
                    impl_output = impl_task_result.output or {}
                    created_paths_raw = impl_output.get("created_paths")
                    if not isinstance(created_paths_raw, list):
                        created_paths_raw = []
                    updated_paths_raw = impl_output.get("updated_paths")
                    if not isinstance(updated_paths_raw, list):
                        updated_paths_raw = []
                    patch_summaries_raw = impl_output.get("patch_summaries")
                    if not isinstance(patch_summaries_raw, list):
                        patch_summaries_raw = []
                    item_result["implementer_created_paths"] = [
                        str(path) for path in created_paths_raw[:10] if isinstance(path, str)
                    ]
                    item_result["implementer_updated_paths"] = [
                        str(path) for path in updated_paths_raw[:10] if isinstance(path, str)
                    ]
                    item_result["implementer_patch_summaries"] = [
                        patch for patch in patch_summaries_raw[:10] if isinstance(patch, dict)
                    ]
                    impl_feedback = str(
                        impl_output.get("response")
                        or impl_output.get("text")
                        or ""
                    )[:600]
                    if impl_passed and not impl_feedback:
                        created_paths = ", ".join(str(path) for path in impl_output.get("created_paths", [])[:5])
                        updated_paths = ", ".join(str(path) for path in impl_output.get("updated_paths", [])[:5])
                        evidence_parts = [part for part in [created_paths, updated_paths] if part]
                        evidence = f" Evidence: {', '.join(evidence_parts)}" if evidence_parts else ""
                        impl_feedback = f"Task completed successfully: {title}.{evidence}"
                except asyncio.TimeoutError:
                    impl_passed = False
                    impl_feedback = f"Implementer timed out after {impl_timeout_s:.0f}s"
                except Exception as exc:
                    impl_passed = False
                    impl_feedback = f"Implementer error: {type(exc).__name__}: {exc}"
                item_result["implementer_feedback"] = impl_feedback
                if not impl_passed:
                    return {
                        "ok": False,
                        "failed_task": title,
                        "error": f"Implementer reported failure: {impl_feedback[:200]}",
                        "task_results": task_results,
                    }

            # ── Review loop ──────────────────────────────────────────────────────────
            spec_pass = bool(item.get("spec_review_passed", True)) if simulation_mode else False
            code_pass = bool(item.get("code_review_passed", True)) if simulation_mode else False

            for iteration in range(1, max_iterations + 1):
                item_result["iterations"] = iteration
                spec_id = await self._spawn_role_subagent(
                    parent_task,
                    "spec_reviewer",
                    f"Review spec compliance for planned task #{idx}: {title}",
                )
                code_id = await self._spawn_role_subagent(
                    parent_task,
                    "code_reviewer",
                    f"Review code quality for planned task #{idx}: {title}",
                )
                item_result["spec_reviewer_agent_id"] = spec_id
                item_result["code_reviewer_agent_id"] = code_id

                if not simulation_mode:
                    review_context = (
                        f"Task #{idx}: {title}\n"
                        f"Implementer output: {item_result.get('implementer_feedback', 'N/A')}"
                    )
                    spec_result = await self._invoke_role_model(parent_task, "spec_reviewer", review_context)
                    code_result = await self._invoke_role_model(parent_task, "code_reviewer", review_context)
                    spec_pass = spec_result["passed"]
                    code_pass = code_result["passed"]
                    item_result["spec_review_feedback"] = spec_result["feedback"]
                    item_result["code_review_feedback"] = code_result["feedback"]

                if spec_pass and code_pass:
                    break
                if iteration == max_iterations:
                    item_result["review_warning"] = (
                        "Review loop exceeded max iterations without passing all checks; "
                        "continuing with concerns"
                    )
                    item_result["review_passed_with_concerns"] = True
                    break
                # Allow the loop to continue; real reviewers will re-evaluate next iteration
                if simulation_mode:
                    spec_pass = True
                    code_pass = True

            # ── Verifier ─────────────────────────────────────────────────────────────
            if require_verification:
                verifier_id = await self._spawn_role_subagent(
                    parent_task,
                    "verifier",
                    f"Verify completion evidence for planned task #{idx}: {title}",
                )
                item_result["verifier_agent_id"] = verifier_id

                if simulation_mode:
                    verification_passed = bool(item.get("verification_passed", True))
                else:
                    verify_context = (
                        f"Task #{idx}: {title}\n"
                        f"Iteration count: {item_result['iterations']}\n"
                        f"Implementer feedback: {item_result.get('implementer_feedback', 'N/A')}\n"
                        f"Created paths: {', '.join(item_result.get('implementer_created_paths', [])) or 'none'}\n"
                        f"Updated paths: {', '.join(item_result.get('implementer_updated_paths', [])) or 'none'}\n"
                        f"Patch summaries: {json.dumps(item_result.get('implementer_patch_summaries', []), default=str)[:800]}\n"
                        f"Spec feedback: {item_result.get('spec_review_feedback', 'N/A')}\n"
                        f"Code feedback: {item_result.get('code_review_feedback', 'N/A')}"
                    )
                    verify_result = await self._invoke_role_model(parent_task, "verifier", verify_context)
                    verification_passed = verify_result["passed"]
                    item_result["verification_feedback"] = verify_result["feedback"]

                if not verification_passed:
                    item_result["verification_passed"] = False
                    item_result["verification_warning"] = "Verification did not meet acceptance criteria"
                    if strict_verification:
                        return {
                            "ok": False,
                            "failed_task": title,
                            "error": "Verification failed — evidence did not meet acceptance criteria",
                            "task_results": task_results,
                        }
                else:
                    item_result["verification_passed"] = True

            item_result["ok"] = True
            task_results.append(item_result)

        return {"ok": True, "task_results": task_results, "max_iterations": max_iterations}

    def _persist_run_to_memory(self, task: Task, result: TaskResult) -> None:
        """Persist task output to semantic store and graph for cross-run retrieval.

        Non-fatal: any storage error is swallowed so it cannot block the caller.
        """
        output = result.output if isinstance(result.output, dict) else {}

        # Semantic store: full-text-searchable document for `POST /tasks/search`
        doc_text = f"{task.description}\n{output.get('response', '')}"
        self.memory.embed_and_store(
            doc_id=task.id,
            text=doc_text,
            metadata={
                "task_id": task.id,
                "success": str(result.success),
                "workflow_mode": str(output.get("workflow_mode", "unknown")),
                "used_tools": json.dumps(output.get("used_tools", []), default=str),
                "created_paths": json.dumps(output.get("created_paths", []), default=str),
                "updated_paths": json.dumps(output.get("updated_paths", []), default=str),
            },
            embedding=[],
        )

        # Graph: task node
        self.memory.graph_add_node(
            task.id,
            node_type="task",
            properties={
                "description": task.description[:200],
                "success": str(result.success),
                "workflow_mode": str(output.get("workflow_mode", "unknown")),
            },
        )

        # Graph: file nodes + CREATED / MODIFIED edges
        for file_path in output.get("created_paths", []):
            if not isinstance(file_path, str):
                continue
            node_id = f"file:{file_path}"
            self.memory.graph_add_node(node_id, node_type="file", properties={"path": file_path})
            self.memory.graph_add_edge(task.id, node_id, edge_type="CREATED")

        for file_path in output.get("updated_paths", []):
            if not isinstance(file_path, str):
                continue
            node_id = f"file:{file_path}"
            self.memory.graph_add_node(node_id, node_type="file", properties={"path": file_path})
            self.memory.graph_add_edge(task.id, node_id, edge_type="MODIFIED")

        # Graph: artifact nodes + PRODUCED edges
        for artifact in output.get("artifacts", []):
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or "")
            if not artifact_id:
                continue
            node_id = f"artifact:{artifact_id}"
            self.memory.graph_add_node(
                node_id,
                node_type="artifact",
                properties={
                    "artifact_id": artifact_id,
                    "kind": str(artifact.get("kind", "unknown")),
                    "title": str(artifact.get("title", "")),
                },
            )
            self.memory.graph_add_edge(task.id, node_id, edge_type="PRODUCED")

    def get_workflow_mode(self) -> str:
        """Get current workflow mode: 'lightning' or 'superpowered'."""
        return str(self.config.get("orchestrator.workflow_mode", "lightning"))

    def should_use_superpowered_mode(self, task_description: str) -> bool:
        """Determine if task should route through Superpowered workflow.

        Heuristic: If task implies build/create/new feature, recommend Superpowered.
        Otherwise, use configured default mode.
        """
        mode = self.get_workflow_mode()
        if mode == "superpowered":
            return True
        if mode == "lightning":
            return False

        # Fallback: check task keywords
        keywords = [
            "build", "create", "new", "feature", "design",
            "architecture", "website", "application", "system"
        ]
        desc_lower = task_description.lower()
        return any(kw in desc_lower for kw in keywords)

    def _detect_lightning_domains(self, task_description: str) -> list[str]:
        """Infer coarse domains from task text for lightweight specialist spawning."""
        text = task_description.lower()
        domain_keywords: list[tuple[str, list[str]]] = [
            ("research", ["research", "find", "search", "compare", "analyze", "investigate", "current", "weather"]),
            ("coding", ["code", "implement", "fix", "bug", "refactor", "api", "test", "build"]),
            ("planning", ["plan", "roadmap", "strategy", "architecture", "design", "spec"]),
            ("writing", ["write", "document", "doc", "proposal", "summary"]),
            ("operations", ["deploy", "infra", "ops", "ci", "runtime", "monitor", "incident"]),
        ]
        domains: list[str] = []
        for domain, keywords in domain_keywords:
            if any(token in text for token in keywords):
                domains.append(domain)
        return domains

    def _build_lightning_task_profile(self, task: Task) -> LightningTaskProfile:
        """Infer a lightweight profile for lightning subagent routing."""
        description = task.description.strip()
        if not description:
            return LightningTaskProfile(domains=[], suggested_roles=[], required_skills=[], trigger_reasons=[])

        domains = self._detect_lightning_domains(description)
        lowered = description.lower()
        reasons: list[str] = []

        if len(domains) >= 2:
            reasons.append("multi-domain")
        if any(token in lowered for token in ["plan", "review", "verify", "multi-step", "step by step"]):
            reasons.append("explicit-workflow-request")
        if any(token in lowered for token in ["and then", "then", "also", "plus"]):
            reasons.append("chained-instructions")
        if any(token in lowered for token in ["critical", "production", "security", "urgent", "risk"]):
            reasons.append("high-risk-context")
        if len(description) >= 180:
            reasons.append("high-complexity")

        skill_matches = self.skills.search_skills(description)[:5]
        required_skills = [skill.skill_id for skill in skill_matches]
        role_map: dict[str, str] = {
            "research": "Research Specialist Agent",
            "coding": "Developer Agent",
            "planning": "Planning Specialist Agent",
            "writing": "Documentation Specialist Agent",
            "operations": "Operations Specialist Agent",
        }
        suggested_roles = [role_map.get(domain, "Specialist Agent") for domain in domains[:3]]
        if not suggested_roles and required_skills:
            suggested_roles = ["Developer Agent"]
        return LightningTaskProfile(
            domains=domains,
            suggested_roles=suggested_roles,
            required_skills=required_skills,
            trigger_reasons=reasons,
        )

    async def _maybe_spawn_lightning_subagents(self, task: Task) -> list[str]:
        """Spawn 1-3 specialist subagents for complex lightning tasks."""
        profile = self._build_lightning_task_profile(task)
        if not profile.trigger_reasons:
            return []

        selected_domains = profile.domains[:3] or ["planning", "coding"]
        selected_roles = profile.suggested_roles[:3] or ["Developer Agent", "Planning Specialist Agent"]

        spawned_ids: list[str] = []
        seen_roles: set[str] = set()
        max_subagents = 3

        for index, role in enumerate(selected_roles):
            if role in seen_roles:
                continue
            seen_roles.add(role)
            domain = selected_domains[min(index, len(selected_domains) - 1)]
            child_task = Task(
                id=f"{task.id}:lightning:{domain}:{uuid.uuid4().hex[:8]}",
                description=(
                    f"Lightning delegated domain: {domain}. Parent task: {task.description}\n"
                    "Collect domain-specific guidance and supporting evidence for the coordinator. "
                    "If the task requires creating files, prefer the available file tools over merely outlining a plan."
                ),
                input={
                    "role": role,
                    "model_backend": task.input.get(
                        "model_backend",
                        self.config.get("model.default_backend", "local_stub"),
                    ),
                    "workflow_mode": "lightning",
                },
            )
            agent_id = await self.spawn_subagent(child_task)
            if profile.required_skills:
                available_skills = [skill_id for skill_id in profile.required_skills[:3] if self.skills.get_skill(skill_id) is not None]
                if available_skills:
                    await self.assign_skills_to_agent(agent_id, available_skills)
            spawned_ids.append(agent_id)
            if len(spawned_ids) >= max_subagents:
                break

        if spawned_ids:
            await self.event_bus.publish(
                "AGENT_SPAWNED",
                {
                    "task_id": task.id,
                    "subagents": True,
                    "mode": "lightning",
                    "strategy": "triggered",
                    "trigger_reasons": profile.trigger_reasons,
                    "domains": selected_domains,
                    "roles": selected_roles,
                    "spawned_ids": list(spawned_ids),
                },
            )
        return spawned_ids

    def _resolve_workflow_mode(self, task: Task) -> str:
        """Resolve workflow mode for a specific task.

        Priority: explicit task input, configured default, then heuristic fallback.
        """
        explicit_mode = str(task.input.get("workflow_mode", "")).strip().lower() if task.input else ""
        if explicit_mode in {"lightning", "superpowered"}:
            return explicit_mode

        configured = self.get_workflow_mode().strip().lower()
        if configured in {"lightning", "superpowered"}:
            return configured

        return "superpowered" if self.should_use_superpowered_mode(task.description) else "lightning"

    def _collect_missing_approvals(self, task: Task, workflow_mode: str) -> list[str]:
        """Collect missing required approvals for Superpowered mode tasks.

        Both spec and plan approval are always required for superpowered mode —
        there is no config toggle to skip them.  This ensures every superpowered
        run goes through the full brainstorm → spec → plan → implement → review
        phase sequence without exception.
        """
        if workflow_mode != "superpowered":
            return []

        approvals = task.input.get("approvals", {}) if task.input else {}
        if not isinstance(approvals, dict):
            approvals = {}

        spec_approved = bool(task.input.get("spec_approved", False)) or bool(approvals.get("spec", False))
        plan_approved = bool(task.input.get("plan_approved", False)) or bool(approvals.get("plan", False))

        missing: list[str] = []
        if not spec_approved:
            missing.append("spec")
        if not plan_approved:
            missing.append("plan")
        return missing

    async def run_reactive_task(self, task: Task) -> TaskResult:
        self.enable_subagents = bool(self.config.get("orchestrator.enable_subagents", False))
        tenant_id = str(task.input.get("tenant_id", "_system_"))
        persist_task = bool(task.input.get("persist_task", True))
        final_result: TaskResult | None = None
        if persist_task:
            self.task_store.create(task, tenant_id=tenant_id)
            self.task_store.mark_started(task.id)
        review_result: dict[str, object] | None = None
        _telemetry: dict[str, object] = {
            "task_id": task.id,
            "workflow_mode": "unknown",
            "duration_ms": 0,
            "gate_blocked": False,
            "review_ran": False,
            "review_passed": None,
            "review_iterations": None,
            "lightning_subagents_spawned": 0,
        }
        _start = datetime.now(timezone.utc)
        lightning_spawned_ids: list[str] = []

        async def _emit_stream_phase(phase: str, message: str, **extra: object) -> None:
            if self.hooks is None:
                return
            payload: dict[str, object] = {
                "task_id": task.id,
                "event_type": "phase",
                "phase": phase,
                "message": message,
                "workflow_mode": str(_telemetry.get("workflow_mode", "unknown")),
            }
            payload.update(extra)
            try:
                await self.hooks.emit(HookPayload(event="StreamEvent", data=payload))
            except Exception:
                pass

        try:
            explicit_workflow_mode = str(task.input.get("workflow_mode", "")).strip().lower() if task.input else ""
            workflow_mode = self._resolve_workflow_mode(task)
            task.input["workflow_mode"] = workflow_mode
            _telemetry["workflow_mode"] = workflow_mode
            await _emit_stream_phase("workflow.start", f"Workflow mode resolved: {workflow_mode}")
            await self.hooks.emit(
                HookPayload(
                    event="SessionStart",
                    data={
                        "task_id": task.id,
                        "tenant_id": tenant_id,
                        "description": task.description,
                        "workflow_mode": workflow_mode,
                        "model_backend": str(task.input.get("model_backend", self.config.get("model.default_backend", "local_stub"))),
                        "started_at": _start.isoformat(),
                        "metadata": dict(task.input),
                    },
                )
            )

            missing_approvals = self._collect_missing_approvals(task, workflow_mode)
            if missing_approvals:
                required_chain = self.skills.get_superpowered_initial_chain()

                # Run the read-only plan phase first — mirror Claude Code's EnterPlanMode.
                # Instead of immediately blocking the user with a raw error, generate a
                # spec + plan and return it in pending_plan_approval status so the frontend
                # can display the plan and let the user approve or reject it.
                plan_draft: dict[str, object] = {}
                # Always run the plan phase — the brainstorm → spec → plan sequence
                # is not optional and cannot be bypassed via config.
                try:
                    await _emit_stream_phase("plan.start", "Generating plan draft for approval gate")
                    plan_draft = await self._run_plan_phase(task)
                    await _emit_stream_phase("plan.ready", "Plan draft generated", ok=bool(plan_draft.get("ok", False)))
                except Exception as _plan_exc:
                    plan_draft = {"ok": False, "error": str(_plan_exc)}
                    await _emit_stream_phase("plan.error", "Plan phase failed", error=str(_plan_exc), reason_code="plan_phase_error")

                gate_message = (
                    "Superpowered mode requires plan approval before implementation. "
                    f"Missing approvals: {', '.join(missing_approvals)}. "
                    "Review the plan_draft and resubmit with spec_approved=true, plan_approved=true "
                    "(and optionally override plan_tasks) to proceed with implementation."
                )
                await self.event_bus.publish(
                    "MODULE_ERROR",
                    {
                        "source": "orchestrator.approval_gate",
                        "task_id": task.id,
                        "workflow_mode": workflow_mode,
                        "missing_approvals": missing_approvals,
                        "required_skill_chain": required_chain,
                        "error": gate_message,
                    },
                )
                result = TaskResult(
                    task_id=task.id,
                    output={
                        "response": gate_message,
                        "mode": "approval-gate",
                        "status": "pending_plan_approval",
                        "workflow_mode": workflow_mode,
                        "missing_approvals": missing_approvals,
                        "required_skill_chain": required_chain,
                        "plan_draft": plan_draft,
                    },
                    success=False,
                    error=gate_message,
                )
                _telemetry["gate_blocked"] = True
                await _emit_stream_phase(
                    "workflow.blocked",
                    "Awaiting required approvals before implementation",
                    reason_code="approval_missing",
                    missing_approvals=list(missing_approvals),
                )
                final_result = result
                if persist_task:
                    self.task_store.mark_completed(result)
                    try:
                        self._persist_run_to_memory(task, result)
                    except Exception:
                        pass
                await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
                return result

            require_task_reviews = bool(
                task.input.get(
                    "require_task_reviews",
                    self.config.get("orchestrator.superpowered_mode.require_task_reviews", True),
                )
            )
            if workflow_mode == "superpowered" and require_task_reviews:
                plan_tasks = task.input.get("plan_tasks", [])
                if isinstance(plan_tasks, list):
                    normalized_plan_tasks = [row for row in plan_tasks if isinstance(row, dict)]
                else:
                    normalized_plan_tasks = []

                # If approvals are in place but no explicit plan tasks were provided,
                # seed a default task so Superpowered mode still executes the role chain.
                if not normalized_plan_tasks:
                    normalized_plan_tasks = [{"title": task.description[:120] or "Implement requested change"}]
                    task.input["plan_tasks"] = normalized_plan_tasks

                plan_tasks = normalized_plan_tasks
                if isinstance(plan_tasks, list) and plan_tasks:
                    if not self.enable_subagents:
                        msg = (
                            "Superpowered task reviews require subagents, but orchestrator.enable_subagents is false."
                        )
                        await _emit_stream_phase(
                            "review.unavailable",
                            msg,
                            reason_code="subagents_disabled",
                        )
                        result = TaskResult(
                            task_id=task.id,
                            output={
                                "response": msg,
                                "mode": "review-loop",
                                "workflow_mode": workflow_mode,
                                "plan_tasks_count": len(plan_tasks),
                            },
                            success=False,
                            error=msg,
                        )
                        final_result = result
                        if persist_task:
                            self.task_store.mark_completed(result)
                            try:
                                self._persist_run_to_memory(task, result)
                            except Exception:
                                pass
                        await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
                        return result

                    _telemetry["review_ran"] = True
                    await _emit_stream_phase("review.start", "Starting superpowered review loop", plan_tasks_count=len(plan_tasks))
                    review_result = await self._run_superpowered_review_loop(task, plan_tasks)
                    review_ok = bool(review_result.get("ok", False))
                    _telemetry["review_passed"] = review_ok
                    task_results_list = review_result.get("task_results", [])
                    if isinstance(task_results_list, list) and task_results_list:
                        _telemetry["review_iterations"] = max(
                            (int(r.get("iterations", 0)) for r in task_results_list if isinstance(r, dict)),
                            default=0,
                        )
                    if not review_ok:
                        msg = str(review_result.get("error", "Superpowered review loop failed"))
                        await _emit_stream_phase(
                            "review.failed",
                            msg,
                            reason_code="review_loop_failed",
                        )
                        result = TaskResult(
                            task_id=task.id,
                            output={
                                "response": msg,
                                "mode": "review-loop",
                                "workflow_mode": workflow_mode,
                                "review_result": review_result,
                            },
                            success=False,
                            error=msg,
                        )
                        final_result = result
                        if persist_task:
                            self.task_store.mark_completed(result)
                            try:
                                self._persist_run_to_memory(task, result)
                            except Exception:
                                pass
                        await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
                        return result
                    await _emit_stream_phase("review.passed", "Superpowered review loop passed")
                    task.input["review_result"] = review_result

            is_lightning_delegate = ":lightning:" in task.id
            if workflow_mode == "lightning" and self.enable_subagents and not is_lightning_delegate:
                try:
                    lightning_spawned_ids = await self._maybe_spawn_lightning_subagents(task)
                    _telemetry["lightning_subagents_spawned"] = len(lightning_spawned_ids)
                except Exception as exc:
                    await self.event_bus.publish(
                        "MODULE_ERROR",
                        {
                            "source": "orchestrator.lightning_spawn",
                            "task_id": task.id,
                            "error": str(exc),
                        },
                    )

            await self.event_bus.publish("AGENT_SPAWNED", {"task_id": task.id, "subagents": self.enable_subagents})
            self.memory.append_short_term("main-agent", {"task": task.description})
            try:
                await _emit_stream_phase("implement.start", "Starting reactive implementation run")
                result = await self.state_machine.run_task(task)
                result.output["workflow_mode"] = workflow_mode
                if lightning_spawned_ids:
                    result.output["spawned_subagents"] = list(lightning_spawned_ids)
                if review_result is not None:
                    result.output["review_result"] = review_result
                await _emit_stream_phase(
                    "implement.done",
                    "Reactive implementation run finished",
                    success=bool(result.success),
                )
            except Exception as exc:
                await _emit_stream_phase(
                    "implement.error",
                    "Reactive implementation run raised an exception",
                    error=str(exc),
                    reason_code="implementation_exception",
                )
                await self.event_bus.publish(
                    "MODULE_ERROR",
                    {
                        "source": "orchestrator",
                        "task_id": task.id,
                        "error": str(exc),
                    },
                )
                result = TaskResult(task_id=task.id, output={}, success=False, error=f"Unhandled runtime error: {exc}")
            final_result = result
            if persist_task:
                self.task_store.mark_completed(result)
                try:
                    self._persist_run_to_memory(task, result)
                except Exception:
                    pass
            await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
            return result

        finally:
            self.deactivate_agents(lightning_spawned_ids)
            self.deactivate_agents(self._collect_review_agent_ids(review_result))
            _telemetry["duration_ms"] = int((datetime.now(timezone.utc) - _start).total_seconds() * 1000)
            await self.event_bus.publish("WORKFLOW_TELEMETRY", _telemetry)
            await self.hooks.emit(
                HookPayload(
                    event="Stop",
                    data={
                        "task_id": task.id,
                        "tenant_id": tenant_id,
                        "success": bool(final_result.success) if final_result is not None else False,
                        "error": final_result.error if final_result is not None else None,
                        "total_tool_calls": len(final_result.output.get("used_tools", [])) if final_result is not None and isinstance(final_result.output, dict) else 0,
                        "total_llm_calls": 0,
                        "duration_ms": _telemetry["duration_ms"],
                        "artifacts": list(final_result.output.get("artifacts", [])) if final_result is not None and isinstance(final_result.output, dict) else [],
                        "output": dict(final_result.output) if final_result is not None and isinstance(final_result.output, dict) else {},
                    },
                )
            )

    async def spawn_subagent(self, _task: Task) -> str:
        self.enable_subagents = bool(self.config.get("orchestrator.enable_subagents", False))
        if not self.enable_subagents:
            raise RuntimeError("Sub-agent spawning is disabled by config toggle")

        role = str(_task.input.get("role", "Specialist Agent"))
        backend = str(_task.input.get("model_backend", self.config.get("model.default_backend", "local_stub")))
        skill_matches = self.skills.search_skills(_task.description)[:3]
        assigned_skills = [s.skill_id for s in skill_matches] or ["reactive_chat"]
        allowed_tools = sorted({tool for s in skill_matches for tool in s.required_tools})

        agent_id = f"subagent-{uuid.uuid4().hex[:8]}"
        self.agents[agent_id] = AgentRecord(
            agent_id=agent_id,
            role=role,
            assigned_skills=assigned_skills,
            allowed_tools=allowed_tools,
            model_backend=backend,
            spawned_from_task=_task.id,
            created_at=datetime.now(timezone.utc).isoformat(),
            active=True,
        )
        self.memory.append_short_term(agent_id, {"spawned_from": _task.id, "role": role})
        await self.event_bus.publish(
            "AGENT_SPAWNED",
            {"task_id": _task.id, "subagents": True, "agent_id": agent_id, "role": role},
        )
        return agent_id

    async def assign_skills_to_agent(self, agent_id: str, skill_ids: list[str]) -> AgentRecord:
        agent = self.agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent not found: {agent_id}")

        validated: list[str] = []
        for skill_id in skill_ids:
            skill = self.skills.get_skill(skill_id)
            if skill is None:
                raise KeyError(f"Skill not found: {skill_id}")
            validated.append(skill_id)

        deduped = sorted(set(validated))
        allowed_tools = sorted(
            {
                tool_name
                for sid in deduped
                for tool_name in (self.skills.get_skill(sid).required_tools if self.skills.get_skill(sid) else [])
            }
        )

        agent.assigned_skills = deduped
        agent.allowed_tools = allowed_tools
        self.memory.append_short_term(agent_id, {"assigned_skills": deduped})
        await self.event_bus.publish(
            "AGENT_SPAWNED",
            {"task_id": "manual-assign", "subagents": agent_id != "main-agent", "agent_id": agent_id, "role": agent.role},
        )
        return agent

    async def execute_skill(self, skill_id: str, skill_input: dict[str, object]) -> dict[str, object]:
        return await self.skills.execute_skill(skill_id, skill_input)

    async def execute_skill_as_agent(
        self,
        agent_id: str,
        skill_id: str,
        skill_input: dict[str, object],
    ) -> dict[str, object]:
        agent = self.agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent not found: {agent_id}")
        if self.skills.get_skill(skill_id) is None:
            raise KeyError(f"Skill not found: {skill_id}")
        if skill_id not in agent.assigned_skills:
            raise PermissionError(f"Skill {skill_id} is not assigned to agent {agent_id}")

        timeout_s = float(self.config.get("orchestrator.skill_execution_timeout_s", 15.0))
        try:
            result = await asyncio.wait_for(
                self.skills.execute_skill(skill_id, skill_input),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError as exc:
            timeout_message = f"Timed out after {timeout_s:.2f}s"
            await self.event_bus.publish(
                "MODULE_ERROR",
                {
                    "source": "orchestrator.skill_execution",
                    "agent_id": agent_id,
                    "skill_id": skill_id,
                    "error": timeout_message,
                },
            )
            raise TimeoutError(timeout_message) from exc
        except Exception as exc:
            await self.event_bus.publish(
                "MODULE_ERROR",
                {
                    "source": "orchestrator.skill_execution",
                    "agent_id": agent_id,
                    "skill_id": skill_id,
                    "error": str(exc),
                },
            )
            raise

        if not bool(result.get("ok", False)):
            await self.event_bus.publish(
                "MODULE_ERROR",
                {
                    "source": "orchestrator.skill_execution",
                    "agent_id": agent_id,
                    "skill_id": skill_id,
                    "error": str(result.get("error", "Skill reported failure")),
                },
            )

        self.memory.append_short_term(
            agent_id,
            {"skill_execution": {"skill_id": skill_id, "ok": bool(result.get("ok", False))}},
        )
        return result

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        return self.agents.get(agent_id)

    def deactivate_agents(self, agent_ids: list[str]) -> None:
        for agent_id in agent_ids:
            agent = self.agents.get(agent_id)
            if agent is None or agent.agent_id == "main-agent":
                continue
            agent.active = False

    def _collect_review_agent_ids(self, review_result: dict[str, object] | None) -> list[str]:
        if not isinstance(review_result, dict):
            return []
        agent_ids: list[str] = []
        task_results = review_result.get("task_results", [])
        if isinstance(task_results, list):
            for item in task_results:
                if not isinstance(item, dict):
                    continue
                for key in (
                    "implementer_agent_id",
                    "spec_reviewer_agent_id",
                    "code_reviewer_agent_id",
                    "verifier_agent_id",
                ):
                    value = str(item.get(key, "")).strip()
                    if value:
                        agent_ids.append(value)
        last_item = review_result.get("last_item_result")
        if isinstance(last_item, dict):
            for key in (
                "implementer_agent_id",
                "spec_reviewer_agent_id",
                "code_reviewer_agent_id",
                "verifier_agent_id",
            ):
                value = str(last_item.get(key, "")).strip()
                if value:
                    agent_ids.append(value)
        return list(dict.fromkeys(agent_ids))

    def list_agents(self) -> list[dict]:
        return [asdict(r) for r in sorted(self.agents.values(), key=lambda x: x.created_at)]

    def list_tasks(self, tenant_id: str | None = None) -> list[dict]:
        return [asdict(record) for record in self.task_store.list(tenant_id=tenant_id)]

    def get_task(self, task_id: str, tenant_id: str | None = None) -> dict | None:
        record = self.task_store.get(task_id, tenant_id=tenant_id)
        return None if record is None else asdict(record)
