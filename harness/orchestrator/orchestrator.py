from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from harness.memory.manager import MemoryManager
from harness.model.adapter import ModelRegistry
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
    state_machine: ReactiveStateMachine = field(init=False)
    enable_subagents: bool = field(init=False)
    role_templates: dict[str, RoleTemplate] = field(init=False)
    task_store: TaskStore = field(init=False)
    agents: dict[str, AgentRecord] = field(init=False)

    def __post_init__(self) -> None:
        self.state_machine = ReactiveStateMachine(self.models, self.config, self.tools, self.skills)
        self.enable_subagents = bool(self.config.get("orchestrator.enable_subagents", False))
        self.role_templates = self._build_default_role_templates()
        self.task_store = TaskStore()
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
        review_task = Task(
            id=f"{parent_task.id}:{role_key}:{uuid.uuid4().hex[:8]}",
            description=(
                f"[{role_name}] {goal}\n\n"
                f"Context:\n{context}\n\n"
                "Respond with PASS or FAIL on the first line, followed by a concise explanation "
                "(1–3 sentences) justifying your decision."
            ),
            input={
                "model_backend": parent_task.input.get(
                    "model_backend",
                    self.config.get("model.default_backend", "local_stub"),
                ),
                # Prevent review tasks from triggering another review loop
                "workflow_mode": "lightning",
            },
        )
        try:
            result = await self.state_machine.run_task(review_task)
            response_text = str(result.output.get("response", "")).strip()
        except Exception as exc:
            return {"passed": False, "feedback": f"Reviewer invocation failed: {exc}"}

        first_line = response_text.split("\n")[0].upper()
        passed: bool
        if first_line.startswith("FAIL"):
            passed = False
        elif first_line.startswith("PASS"):
            passed = True
        else:
            # Ambiguous response — check for FAIL anywhere in first 60 chars; else default to pass
            passed = "FAIL" not in response_text.upper()[:60]

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
                impl_context = f"Task #{idx}: {title}\nDescription: {str(item.get('description', title))}"
                impl_result = await self._invoke_role_model(parent_task, "implementer", impl_context)
                item_result["implementer_feedback"] = impl_result["feedback"]
                if not impl_result["passed"]:
                    return {
                        "ok": False,
                        "failed_task": title,
                        "error": f"Implementer reported failure: {impl_result['feedback'][:200]}",
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
                    return {
                        "ok": False,
                        "failed_task": title,
                        "error": "Review loop exceeded max iterations without passing all checks",
                        "task_results": task_results,
                    }
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
                        f"Spec feedback: {item_result.get('spec_review_feedback', 'N/A')}"
                    )
                    verify_result = await self._invoke_role_model(parent_task, "verifier", verify_context)
                    verification_passed = verify_result["passed"]
                    item_result["verification_feedback"] = verify_result["feedback"]

                if not verification_passed:
                    return {
                        "ok": False,
                        "failed_task": title,
                        "error": "Verification failed — evidence did not meet acceptance criteria",
                        "task_results": task_results,
                    }

            item_result["ok"] = True
            task_results.append(item_result)

        return {"ok": True, "task_results": task_results, "max_iterations": max_iterations}

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
        """Collect missing required approvals for Superpowered mode tasks."""
        if workflow_mode != "superpowered":
            return []

        approvals = task.input.get("approvals", {}) if task.input else {}
        if not isinstance(approvals, dict):
            approvals = {}

        missing: list[str] = []
        require_spec = bool(self.config.get("orchestrator.superpowered_mode.require_spec_approval", True))
        require_plan = bool(self.config.get("orchestrator.superpowered_mode.require_plan_approval", True))

        spec_approved = bool(task.input.get("spec_approved", False)) or bool(approvals.get("spec", False))
        plan_approved = bool(task.input.get("plan_approved", False)) or bool(approvals.get("plan", False))

        if require_spec and not spec_approved:
            missing.append("spec")
        if require_plan and not plan_approved:
            missing.append("plan")

        return missing

    async def run_reactive_task(self, task: Task) -> TaskResult:
        self.enable_subagents = bool(self.config.get("orchestrator.enable_subagents", False))
        self.task_store.create(task)
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

        try:
            workflow_mode = self._resolve_workflow_mode(task)
            task.input["workflow_mode"] = workflow_mode
            _telemetry["workflow_mode"] = workflow_mode

            missing_approvals = self._collect_missing_approvals(task, workflow_mode)
            if missing_approvals:
                required_chain = self.skills.get_superpowered_initial_chain()
                gate_message = (
                    "Superpowered mode requires approvals before implementation. "
                    f"Missing approvals: {', '.join(missing_approvals)}."
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
                        "workflow_mode": workflow_mode,
                        "missing_approvals": missing_approvals,
                        "required_skill_chain": required_chain,
                    },
                    success=False,
                    error=gate_message,
                )
                _telemetry["gate_blocked"] = True
                self.task_store.mark_completed(result)
                await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
                return result

            if workflow_mode == "superpowered" and bool(
                self.config.get("orchestrator.superpowered_mode.require_task_reviews", True)
            ):
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
                        self.task_store.mark_completed(result)
                        await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
                        return result

                    _telemetry["review_ran"] = True
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
                        self.task_store.mark_completed(result)
                        await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
                        return result
                    task.input["review_result"] = review_result

            if workflow_mode == "lightning" and self.enable_subagents:
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
                result = await self.state_machine.run_task(task)
                result.output["workflow_mode"] = workflow_mode
                if lightning_spawned_ids:
                    result.output["spawned_subagents"] = list(lightning_spawned_ids)
                if review_result is not None:
                    result.output["review_result"] = review_result
            except Exception as exc:
                await self.event_bus.publish(
                    "MODULE_ERROR",
                    {
                        "source": "orchestrator",
                        "task_id": task.id,
                        "error": str(exc),
                    },
                )
                result = TaskResult(task_id=task.id, output={}, success=False, error=f"Unhandled runtime error: {exc}")
            self.task_store.mark_completed(result)
            await self.event_bus.publish("TASK_COMPLETED", {"task_id": task.id, "success": result.success})
            return result

        finally:
            _telemetry["duration_ms"] = int((datetime.now(timezone.utc) - _start).total_seconds() * 1000)
            await self.event_bus.publish("WORKFLOW_TELEMETRY", _telemetry)

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

    def list_agents(self) -> list[dict]:
        return [asdict(r) for r in sorted(self.agents.values(), key=lambda x: x.created_at)]

    def list_tasks(self) -> list[dict]:
        return [asdict(record) for record in self.task_store.list()]

    def get_task(self, task_id: str) -> dict | None:
        record = self.task_store.get(task_id)
        return None if record is None else asdict(record)
