# TitanShift Harness Test Matrix

## Purpose
This matrix defines repeatable tests for reliability, skill usage, and creator workflows.

## Test Artifact Location Policy
All test-generated artifacts must be written under a dedicated testing root to avoid repository clutter.

Required location
- Use `Testing/` as the top-level folder for all matrix runs.
- Use per-suite subfolders:
	- `Testing/P0_core_reliability/`
	- `Testing/P1_frontend_quality/`
	- `Testing/P2_web_file_integrity/`
	- `Testing/P3_skill_activation/`
	- `Testing/P4_creator_use_cases/`
	- `Testing/P5_regression_gate/`

Rules
- No generated test files in repo root.
- Each run writes to `Testing/<suite>/<timestamp_or_run_id>/`.
- Keep raw outputs (generated files), tool telemetry, and summary report together per run.
- Include at least one `report.json` per run with pass/fail and evidence paths.

## P0 Core Reliability (Blocker)
1. Mode routing
- Verify lightning prompt resolves to lightning in task output.
- Verify superpowered prompt resolves to superpowered in task output.
- Verify /chat/stream with superpowered routes through orchestrator phases.

2. Timeout layering
- Cases: model timeout 60/180/600, run timeout 60/180/600.
- Assert no hidden 300s timeout in superpowered implementer.
- Assert graceful fallback when model times out after tool success.

3. Tool truthfulness
- If response claims file creation/update, assert created_paths/updated_paths and used_tools include matching write/append tools.
- Reject success if narrative claims side-effects not present in telemetry.

4. Cancellation and zombie-run cleanup
- Cancel active run and assert status transitions to cancelled.
- Restart API, then cancel stale running task and assert forced cancellation succeeds.

5. Concurrency and queue safety
- At capacity, API returns 429 with Retry-After.
- No stream endpoint bypass of queue limits.

## P1 Frontend Creator Quality (Blocker)
1. Single-file landing page generation
- Prompt for one self-contained index.html.
- Assert embedded CSS exists and page is visually styled.

2. Multi-file generation
- Prompt for index.html + style.css.
- Assert both files exist and stylesheet is linked correctly.

3. SVG and visual art
- Prompt requires inline SVG and one decorative vector element.
- Assert valid <svg> appears and renders in browser.

4. Responsiveness
- Assert viewport meta exists.
- Assert at least one media query and usable mobile layout.

5. Non-trivial quality bar
- Assert modern typography, spacing system, color contrast, and clear hierarchy.

6. Video landing companion assets
- Prompt for a landing page plus a short promo video concept package.
- Assert generation of storyboard/shot list artifact and scene timing breakdown.
- Assert all outputs are saved under `Testing/P1_frontend_quality/...`.

## P2 Web + File Workflow Integrity
1. Fetch then write
- Acquire data from web and append to file in one run.
- Assert link/value present in file and tool telemetry matches.

2. Website hardening
- Test blocked pages and JS-heavy pages.
- Assert fallback strategy: web_fetch first, escalate only when needed.

3. Evidence and provenance
- Assert browser_proof/final_url present for web-derived outputs.

4. Anti-hallucination completion
- If required tools specified, assert each required tool was attempted before completion.

## P3 Skill Activation Coverage
For each installed skill, run one positive and one negative test where applicable:
- brainstorming
- code-reviewer
- coding-standards
- frontend-design
- impeccable
- last30days
- observability-designer
- pr-review-expert
- product-manager-toolkit
- senior-security
- subagent-driven-development
- test-driven-development
- ui-ux-pro-max
- verification-before-completion
- writing-plans

For each skill test, assert:
1. The task behavior reflects the skill intent.
2. Tool selection aligns with the domain.
3. Output quality meets acceptance criteria.
4. No non-existent tool calls are emitted.

## P4 Creator Use Cases
1. Landing page from prompt to browser preview.
2. Video script + scene plan generation.
3. Research brief with citations from web.
4. File refactor and test-update workflow.
5. Multi-artifact delivery (doc + code + media manifest).

6. Video generation workflow (media artifacts)
- Prompt for a creator-ready video package:
	- script,
	- shot list,
	- scene timing CSV,
	- voiceover text,
	- thumbnail prompt,
	- Remotion MP4 render artifact,
	- HyperFrames scene + render-job JSON.
- Assert artifacts are created under `Testing/P4_creator_use_cases/video_generation/...`.
- Assert outputs include machine-usable metadata (durations, aspect ratio, target platform).
- Assert `generate_remotion_video` produces an actual `.mp4` file in the target path.
- Assert `generate_hyperframes_scene` appears in tool telemetry for deterministic video runs.
- Assert artifacts include kinds `video.hyperframes.scene` and `video.hyperframes.render_job`.
- Assert render-job metadata includes `composition_id`, `scene_path`, and intended `output_mp4`.
- Note: current implementation guarantees scene/job generation; MP4 render execution is performed by HyperFrames runtime/CLI from that job config.

7. PDF artifact workflow
- Prompt for a deterministic PDF report artifact.
- Assert `generate_report` with `format=pdf` is used.
- Assert generated files are non-empty and located under `Testing/P4_creator_use_cases/pdf/...`.
- Assert naming convention includes run id and artifact purpose.

8. Artifact flood guard
- Run mixed creator prompt (web + code + media + documents).
- Assert no generated file path is outside `Testing/`.
- Fail run if any root-level artifact is created.

## P5 Regression Gate
Required green checks before release:
1. P0 suite 100% pass.
2. P1 suite 100% pass.
3. No zombie running tasks in task store.
4. No response-side effect mismatch in sampled runs.
5. Superpowered and stream paths both complete for representative creator prompts.
6. Video-generation use case pass with complete metadata outputs.
7. PDF artifact scenario pass with telemetry evidence and files under `Testing/` only.
